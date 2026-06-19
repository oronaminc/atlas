"""Integration: the correlation loop with the threshold filter (mock Mimir).
A below-threshold event is stored + suppressed (no incident, terminal);
an above-threshold event is escalated to an incident."""

from sqlalchemy import select

from app.models.alerting import AlertEvent, Incident
from app.models.threshold import RuleCatalog, ThresholdOverride
from app.services.correlation.config import get_config
from app.services.correlation.dedup import InMemoryDedupStore
from app.services.correlation.engine import CorrelationEngine
from app.services.correlation.strategy import AttributeTimeStrategy
from app.services.threshold import ValueCache, should_suppress
from app.workers.correlation_worker import claim_events, to_normalized
from tests.notifications.helpers import NOW


def _event(db, cmdb, name="HostOutOfMemory"):
    e = AlertEvent(
        fingerprint=f"fp-{cmdb}",
        source="am",
        name=name,
        severity="critical",
        status="firing",
        labels={"cmdb_ci": cmdb},
        annotations={},
        starts_at=NOW,
        received_at=NOW,
    )
    db.add(e)
    return e


async def test_threshold_filter_in_correlation_loop(db):
    db.add(
        RuleCatalog(
            alertname="HostOutOfMemory", comparator=">", value_query='m{cmdb_ci="{{cmdb_ci}}"}'
        )
    )
    db.add(
        ThresholdOverride(
            alertname="HostOutOfMemory", tier="server", target_cmdb_ci="LOW", value=95
        )
    )
    db.add(
        ThresholdOverride(
            alertname="HostOutOfMemory", tier="server", target_cmdb_ci="HIGH", value=95
        )
    )
    _event(db, "LOW")  # value 92 < 95 -> suppress
    _event(db, "HIGH")  # value 97 >= 95 -> pass -> incident
    await db.commit()

    async def fetch_value(_tid, promql):
        return 92.0 if '"LOW"' in promql else 97.0

    engine = CorrelationEngine(
        dedup_store=InMemoryDedupStore(), strategies=[AttributeTimeStrategy()]
    )
    cache = ValueCache()
    config = await get_config(db)
    for event in await claim_events(db, worker_id="w", now=NOW):
        suppress, value = await should_suppress(db, event, fetch_value=fetch_value, cache=cache)
        if value is not None:
            event.value = value
        if suppress:
            event.suppressed = True
            continue
        await engine.correlate(db, event, to_normalized(event), config, now=NOW)
    await db.commit()

    events = {e.labels["cmdb_ci"]: e for e in (await db.execute(select(AlertEvent))).scalars()}
    low, high = events["LOW"], events["HIGH"]
    assert low.suppressed is True and low.incident_id is None and low.value == 92.0
    assert high.suppressed is False and high.incident_id is not None and high.value == 97.0
    assert (await db.execute(select(Incident))).scalars().first() is not None

    # suppressed event is terminal: a re-claim does NOT pick it up again
    again = await claim_events(db, worker_id="w", now=NOW)
    assert all(e.id != low.id for e in again)
