"""IMP stage 3: C1 topology correlation engine — the full SQLite matrix.

Severity-aware formation (critical forms at 1, warning/info at 2 with
retro-attach), the FREE/correlated/retro-attach state machine, manual
promote/attach/detach. Drives the engine through a worker-style loop on the
`db` fixture (the real worker uses async_session_factory; the loop body here is
identical to correlation_worker.correlate_pending)."""

from datetime import timedelta

from sqlalchemy import func, select

from app.models.alerting import AlertEvent, Incident, IncidentStatus
from app.models.base import utcnow
from app.services.correlation.dedup import InMemoryDedupStore
from app.services.correlation.engine import latest_other_event
from app.services.grouping_config import get_active_rule
from app.services.incident_service import (
    AlreadyAttachedError,
    attach_to_incident,
    detach_alert,
    group_alert,
    promote_alert,
)
from app.services.threshold import should_suppress
from app.workers.correlation_worker import claim_events

NOW = utcnow()
L2 = "sub20251126_1040230842"


def alert(sev="warning", l2=L2, fp=None, received=None, **labels):
    rec = received or NOW
    base = {"cmdb_service_l2_code": l2, "cmdb_service_l1_code": "ssm_l1", "cmdb_zone": "z"}
    base.update(labels)
    return AlertEvent(
        fingerprint=fp or f"fp-{sev}-{l2}-{rec.isoformat()}-{len(labels)}",
        source="alertmanager",
        name="HostHighCpuLoad",
        severity=sev,
        status="firing",
        labels={"cmdb_service_l2": "[SPACE]GIANT", **base},
        annotations={},
        starts_at=rec,
        received_at=rec,
        cmdb_service_l2_code=l2,
        cmdb_service_l1_code=base.get("cmdb_service_l1_code"),
        cmdb_zone=base.get("cmdb_zone"),
    )


async def run_worker(db, now=NOW, dedup=None):
    """Replicates correlation_worker.correlate_pending on the test session."""
    dedup = dedup or InMemoryDedupStore()
    rule = await get_active_rule(db)
    for ev in await claim_events(db, worker_id="w", now=now):
        if ev.incident_id is not None:
            ev.correlated = True
            continue
        key = ev.fingerprint
        if await dedup.seen_within(key, rule.dedup_window_seconds):
            prior = await latest_other_event(
                db, ev, window_seconds=rule.dedup_window_seconds, now=now
            )
            if prior is not None:
                prior.dedup_count += 1
                await db.delete(ev)
                continue
        suppress, value = await should_suppress(db, ev)
        if value is not None:
            ev.value = value
        if suppress:
            ev.suppressed = True
            ev.correlated = True
            continue
        await group_alert(db, ev, rule, now)
        ev.correlated = True
    await db.flush()


async def _incidents(db):
    return (await db.execute(select(Incident))).scalars().all()


async def _count_incidents(db):
    return (await db.execute(select(func.count()).select_from(Incident))).scalar_one()


# ---------- severity-aware formation ----------
async def test_critical_forms_immediately_size_1(db):
    db.add(alert(sev="critical"))
    await run_worker(db)
    incs = await _incidents(db)
    assert len(incs) == 1
    assert incs[0].alert_count == 1 and incs[0].severity == "critical"
    assert incs[0].origin == "auto" and incs[0].group_key == f"cmdb_service_l2_code={L2}"


async def test_single_warning_stays_free(db):
    db.add(alert(sev="warning"))
    await run_worker(db)
    assert await _count_incidents(db) == 0
    ev = (await db.execute(select(AlertEvent))).scalar_one()
    assert ev.incident_id is None and ev.correlated is True  # FREE, processed


async def test_two_warnings_form_with_retro_attach(db):
    w1 = alert(sev="warning", fp="w1")
    db.add(w1)
    await run_worker(db)  # w1 free
    assert await _count_incidents(db) == 0
    db.add(alert(sev="warning", fp="w2", received=NOW + timedelta(minutes=2)))
    await run_worker(db, now=NOW + timedelta(minutes=2))  # w2 forms + retro-attaches w1
    incs = await _incidents(db)
    assert len(incs) == 1 and incs[0].alert_count == 2
    # the EARLIER free alert was pulled in by the 2nd (retro-attach). The bulk
    # UPDATE bypassed the identity map, so refresh to read the committed truth.
    w1r = (await db.execute(select(AlertEvent).where(AlertEvent.fingerprint == "w1"))).scalar_one()
    await db.refresh(w1r)
    assert w1r.incident_id == incs[0].id


async def test_info_needs_two(db):
    db.add(alert(sev="info", fp="i1"))
    await run_worker(db)
    assert await _count_incidents(db) == 0
    db.add(alert(sev="info", fp="i2", received=NOW + timedelta(minutes=1)))
    await run_worker(db, now=NOW + timedelta(minutes=1))
    assert await _count_incidents(db) == 1


async def test_critical_retro_attaches_free_warning(db):
    db.add(alert(sev="warning", fp="w"))
    await run_worker(db)  # warning free
    db.add(alert(sev="critical", fp="c", received=NOW + timedelta(minutes=1)))
    await run_worker(db, now=NOW + timedelta(minutes=1))  # critical forms, pulls warning in
    incs = await _incidents(db)
    assert len(incs) == 1 and incs[0].alert_count == 2 and incs[0].severity == "critical"


async def test_out_of_window_warning_stays_free(db):
    db.add(alert(sev="warning", fp="w1"))
    await run_worker(db)
    later = NOW + timedelta(seconds=1000)  # > 900s window
    db.add(alert(sev="warning", fp="w2", received=later))
    await run_worker(db, now=later)
    assert await _count_incidents(db) == 0  # w1 out of window, not counted/retro'd


async def test_missing_topology_label_stays_free(db):
    ev = alert(sev="critical", fp="nokey")
    ev.cmdb_service_l2_code = None
    ev.labels = {k: v for k, v in ev.labels.items() if k != "cmdb_service_l2_code"}
    db.add(ev)
    await run_worker(db)
    assert await _count_incidents(db) == 0
    got = (await db.execute(select(AlertEvent))).scalar_one()
    assert got.incident_id is None and got.correlated is True


async def test_ongoing_alert_attaches_to_open_incident(db):
    db.add(alert(sev="critical", fp="c1"))
    await run_worker(db)  # forms incident
    db.add(alert(sev="warning", fp="c2", received=NOW + timedelta(minutes=3)))
    await run_worker(db, now=NOW + timedelta(minutes=3))
    incs = await _incidents(db)
    assert len(incs) == 1 and incs[0].alert_count == 2


async def test_resolved_incident_not_reopened(db):
    db.add(alert(sev="critical", fp="c1"))
    await run_worker(db)
    inc = (await _incidents(db))[0]
    inc.status = IncidentStatus.resolved
    await db.flush()
    db.add(alert(sev="critical", fp="c2", received=NOW + timedelta(minutes=2)))
    await run_worker(db, now=NOW + timedelta(minutes=2))
    assert await _count_incidents(db) == 2  # new incident, resolved one untouched


async def test_free_alert_not_reclaimed(db):
    db.add(alert(sev="warning", fp="lone"))
    await run_worker(db)  # -> free, correlated
    # a fresh claim must NOT return the free alert again
    again = await claim_events(db, worker_id="w2", now=NOW + timedelta(minutes=1))
    assert again == []


# ---------- dedup + threshold interplay ----------
async def test_dedup_collapses_before_grouping(db):
    store = InMemoryDedupStore()  # shared across batches, like the real worker
    db.add(alert(sev="critical", fp="dup"))
    await run_worker(db, dedup=store)  # forms incident (1 alert)
    # identical fingerprint within dedup window -> collapses into prior, no new alert
    db.add(alert(sev="critical", fp="dup", received=NOW + timedelta(seconds=30)))
    await run_worker(db, now=NOW + timedelta(seconds=30), dedup=store)
    n_alerts = (await db.execute(select(func.count()).select_from(AlertEvent))).scalar_one()
    assert n_alerts == 1  # second collapsed
    assert await _count_incidents(db) == 1


# ---------- manual promote / attach / detach ----------
async def test_manual_promote_single_alert(db):
    a = alert(sev="warning", fp="m")
    db.add(a)
    await db.flush()
    inc = await promote_alert(db, a, NOW, title="manual sit")
    assert inc.origin == "manual" and inc.alert_count == 1 and inc.title == "manual sit"
    assert a.incident_id == inc.id and a.correlated is True
    assert inc.group_key is None  # manual incidents carry no topology key


async def test_manual_attach_and_already_attached_409(db):
    # two separate incidents (manual promotes; no shared topology key)
    a = alert(sev="warning", fp="a")
    free = alert(sev="info", fp="free", l2="OTHER_L2")  # different l2 -> stays free alone
    db.add_all([a, free])
    await run_worker(db)  # both lone non-criticals -> FREE, no incidents
    assert await _count_incidents(db) == 0

    incA = await promote_alert(db, a, NOW)  # manual incident from a
    await db.flush()
    await attach_to_incident(db, incA, free, NOW)  # manually add the free alert
    assert free.incident_id == incA.id

    # attaching the now-attached alert to a DIFFERENT incident raises (decision H)
    b = alert(sev="warning", fp="b", l2="THIRD")
    db.add(b)
    await db.flush()
    incB = await promote_alert(db, b, NOW)
    raised = False
    try:
        await attach_to_incident(db, incB, free, NOW)
    except AlreadyAttachedError:
        raised = True
    assert raised


async def test_detach_last_alert_forbidden(db):
    # A4 (replaces decision D): detaching the only alert is forbidden — an
    # incident can never have 0 alerts; dissolve it with delete_incident instead.
    import pytest

    from app.services.incident_service import LastAlertError

    a = alert(sev="critical", fp="solo")
    db.add(a)
    await run_worker(db)
    inc = (await _incidents(db))[0]
    with pytest.raises(LastAlertError):
        await detach_alert(db, inc, a, NOW)
