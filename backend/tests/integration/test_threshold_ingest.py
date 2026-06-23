"""Integration: the correlation loop with the no-PromQL threshold filter.
A below-threshold event is stored + suppressed (no incident, terminal);
an above-threshold event is escalated to an incident. The alert carries its own
value; the comparator comes from its annotations; the override sets the number."""

from sqlalchemy import select

from app.models.alerting import AlertEvent, Incident
from app.models.threshold import ThresholdOverride
from app.services.grouping_config import get_active_rule
from app.services.incident_service import group_alert
from app.services.threshold import should_suppress
from app.workers.correlation_worker import claim_events
from tests.notifications.helpers import NOW


def _event(db, cmdb, value, name="HostOutOfMemory"):
    e = AlertEvent(
        fingerprint=f"fp-{cmdb}",
        source="am",
        name=name,
        severity="critical",
        status="firing",
        labels={"cmdb_ci": cmdb, "cmdb_service_l2_code": f"L2-{cmdb}"},
        annotations={"atlas_compare": ">"},  # comparator only; number = the override
        starts_at=NOW,
        received_at=NOW,
        value=value,
        cmdb_service_l2_code=f"L2-{cmdb}",
    )
    db.add(e)
    return e


async def test_threshold_filter_in_correlation_loop(db):
    db.add(ThresholdOverride(alertname="HostOutOfMemory", target_cmdb_ci="LOW", value=95))
    db.add(ThresholdOverride(alertname="HostOutOfMemory", target_cmdb_ci="HIGH", value=95))
    _event(db, "LOW", 92.0)  # 92 < 95 -> suppress
    _event(db, "HIGH", 97.0)  # 97 >= 95 -> pass -> incident
    await db.commit()

    rule = await get_active_rule(db)
    for event in await claim_events(db, worker_id="w", now=NOW):
        suppress, value = await should_suppress(db, event)
        if value is not None:
            event.value = value
        if suppress:
            event.suppressed = True
            event.correlated = True
            continue
        await group_alert(db, event, rule, NOW)
        event.correlated = True
    await db.commit()

    events = {e.labels["cmdb_ci"]: e for e in (await db.execute(select(AlertEvent))).scalars()}
    low, high = events["LOW"], events["HIGH"]
    assert low.suppressed is True and low.incident_id is None and low.value == 92.0
    assert high.suppressed is False and high.incident_id is not None and high.value == 97.0
    assert (await db.execute(select(Incident))).scalars().first() is not None

    # suppressed event is terminal: a re-claim does NOT pick it up again
    again = await claim_events(db, worker_id="w", now=NOW)
    assert all(e.id != low.id for e in again)
