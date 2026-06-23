"""Stage 5 incident semantics: delete (dissolve), detach-last guard, AM-resolved
auto-resolve (per-element/batched), all-alerts-resolved -> incident resolved
(via both AM-resolve and detach), freed-alert re-attach."""

import pytest
from sqlalchemy import func, select

from app.models.alerting import AlertEvent, Incident, IncidentEvent, IncidentStatus
from app.models.base import utcnow
from app.models.delivery import Notification
from app.services import incident_service
from app.services.correlation.fingerprint import compute_fingerprint

pytestmark = pytest.mark.asyncio
NOW = utcnow()


def _alert(name, *, status="firing", labels=None, value=None):
    lbls = labels or {"cmdb_ci": f"CI-{name}", "cmdb_service_l2_code": "L2X"}
    return AlertEvent(
        fingerprint=compute_fingerprint("alertmanager", name, lbls),
        source="alertmanager",
        name=name,
        severity="warning",
        status=status,
        labels=lbls,
        annotations={},
        starts_at=NOW,
        received_at=NOW,
        cmdb_service_l2_code=lbls.get("cmdb_service_l2_code"),
    )


async def _incident_with(db, alerts):
    inc = Incident(
        title="t",
        status=IncidentStatus.open,
        severity="warning",
        group_key="cmdb_service_l2_code=L2X",
        first_seen=NOW,
        last_seen=NOW,
        alert_count=len(alerts),
        cmdb_service_l2_code="L2X",
    )
    db.add(inc)
    await db.flush()
    for a in alerts:
        a.incident_id = inc.id
        a.correlated = True
        db.add(a)
    await db.flush()
    return inc


async def test_detach_last_alert_forbidden(db):
    inc = await _incident_with(db, [_alert("A")])
    alert = (await db.execute(select(AlertEvent))).scalar_one()
    with pytest.raises(incident_service.LastAlertError):
        await incident_service.detach_alert(db, inc, alert, NOW)


async def test_detach_then_reattach_freed_alert(db):
    a, b = _alert("A"), _alert("B")
    inc = await _incident_with(db, [a, b])
    await incident_service.detach_alert(db, inc, a, NOW)
    assert a.incident_id is None and a.correlated is True  # freed, not re-grouped
    assert inc.alert_count == 1
    # freed alert is accepted by manual promote (A4)
    new_inc = await incident_service.promote_alert(db, a, NOW)
    assert new_inc.id != inc.id and a.incident_id == new_inc.id


async def test_delete_incident_frees_alerts_keeps_sent(db):
    a, b = _alert("A"), _alert("B")
    inc = await _incident_with(db, [a, b])
    db.add_all(
        [
            Notification(incident_id=inc.id, channel="email", recipient_address="x", status="sent"),
            Notification(
                incident_id=inc.id, channel="email", recipient_address="y", status="pending"
            ),
        ]
    )
    await db.flush()
    freed = await incident_service.delete_incident(db, inc)
    await db.commit()
    db.expunge_all()  # drop stale identity-map copies; read DB truth
    assert freed == 2
    assert (await db.execute(select(func.count()).select_from(Incident))).scalar_one() == 0
    # alerts freed, still present
    alerts = list((await db.execute(select(AlertEvent))).scalars())
    assert len(alerts) == 2 and all(x.incident_id is None for x in alerts)
    # pending dropped, sent kept (orphaned)
    notifs = list((await db.execute(select(Notification))).scalars())
    assert len(notifs) == 1 and notifs[0].status == "sent" and notifs[0].incident_id is None


async def test_am_resolved_auto_resolves_alert_and_incident(db):
    a = _alert("A")
    inc = await _incident_with(db, [a])
    await db.commit()
    # AM sends resolved for A -> system-resolves it, and since it's the only alert
    # the incident auto-resolves
    matched = await incident_service.resolve_incoming(db, "alertmanager", "A", a.labels, NOW)
    await db.commit()
    assert matched is True
    await db.refresh(a)
    await db.refresh(inc)
    assert a.status == "resolved"
    assert inc.status == IncidentStatus.resolved
    kinds = [e.kind for e in (await db.execute(select(IncidentEvent))).scalars()]
    assert "alert_resolved" in kinds and "status_changed" in kinds


async def test_incident_resolves_only_when_all_alerts_resolved(db):
    a, b = _alert("A"), _alert("B")
    inc = await _incident_with(db, [a, b])
    await db.commit()
    await incident_service.resolve_incoming(db, "alertmanager", "A", a.labels, NOW)
    await db.commit()
    await db.refresh(inc)
    assert inc.status == IncidentStatus.open  # B still firing
    await incident_service.resolve_incoming(db, "alertmanager", "B", b.labels, NOW)
    await db.commit()
    await db.refresh(inc)
    assert inc.status == IncidentStatus.resolved  # both resolved


async def test_suppressed_incident_resolves_when_all_resolved(db):
    a = _alert("A")
    inc = await _incident_with(db, [a])
    inc.status = IncidentStatus.suppressed
    await db.commit()
    await incident_service.resolve_incoming(db, "alertmanager", "A", a.labels, NOW)
    await db.commit()
    await db.refresh(inc)
    assert inc.status == IncidentStatus.resolved


async def test_detach_triggers_all_resolved(db):
    # incident with one resolved + one firing; detaching the firing one leaves all
    # resolved -> incident resolves
    a = _alert("A", status="resolved")
    b = _alert("B")
    c = _alert("C")
    inc = await _incident_with(db, [a, b, c])
    await incident_service.detach_alert(db, inc, b, NOW)  # leaves A(resolved)+C(firing)
    await db.commit()
    await db.refresh(inc)
    assert inc.status == IncidentStatus.open
    await incident_service.detach_alert(db, inc, c, NOW)  # leaves only A(resolved)
    await db.commit()
    await db.refresh(inc)
    assert inc.status == IncidentStatus.resolved


async def test_am_resolved_no_match_is_noop(db):
    matched = await incident_service.resolve_incoming(
        db, "alertmanager", "Ghost", {"cmdb_ci": "none"}, NOW
    )
    assert matched is False
