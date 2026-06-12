"""Stage 1→2→3 orchestration through CorrelationEngine.process()."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models.alerting import AlertEvent, Incident, IncidentEvent, IncidentStatus
from app.services.correlation.config import get_config
from app.services.correlation.dedup import InMemoryDedupStore
from app.services.correlation.engine import CorrelationEngine
from app.services.correlation.strategy import AttributeTimeStrategy
from tests.correlation.helpers import alert

NOW = datetime(2026, 6, 10, 1, 0, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_engine(clock: FakeClock | None = None) -> CorrelationEngine:
    return CorrelationEngine(
        dedup_store=InMemoryDedupStore(clock=clock or FakeClock()),
        strategies=[AttributeTimeStrategy()],
    )


async def count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_first_alert_creates_incident_with_timeline(db):
    engine = make_engine()
    config = await get_config(db)

    event = await engine.process(db, alert(), config, now=NOW)
    await db.commit()

    assert event.incident_id is not None
    assert event.fingerprint
    incident = await db.get(Incident, event.incident_id)
    assert incident.status == IncidentStatus.open
    assert incident.group_key == "host=web-01"
    assert incident.alert_count == 1
    assert incident.severity == "critical"

    kinds = [
        e.kind
        for e in (
            await db.execute(select(IncidentEvent).where(IncidentEvent.incident_id == incident.id))
        ).scalars()
    ]
    assert "created" in kinds
    assert "alert_attached" in kinds


async def test_duplicate_within_window_increments_count_no_new_row(db):
    engine = make_engine()
    config = await get_config(db)

    first = await engine.process(db, alert(), config, now=NOW)
    second = await engine.process(db, alert(), config, now=NOW + timedelta(minutes=1))
    await db.commit()

    assert second.id == first.id
    assert second.dedup_count == 2
    assert await count(db, AlertEvent) == 1
    incident = await db.get(Incident, first.incident_id)
    assert incident.alert_count == 1


async def test_duplicate_after_window_creates_new_row(db):
    clock = FakeClock()
    engine = make_engine(clock)
    config = await get_config(db)

    first = await engine.process(db, alert(), config, now=NOW)
    clock.t += config.dedup_window_seconds + 1
    second = await engine.process(
        db,
        alert(),
        config,
        now=NOW + timedelta(seconds=config.dedup_window_seconds + 1),
    )
    await db.commit()

    assert second.id != first.id
    assert await count(db, AlertEvent) == 2


async def test_cross_source_alerts_sharing_host_group_into_one_incident(db):
    engine = make_engine()
    config = await get_config(db)

    cpu = await engine.process(db, alert(name="HighCPU", severity="warning"), config, now=NOW)
    disk = await engine.process(
        db,
        alert(name="DiskFull", source="datadog", severity="critical"),
        config,
        now=NOW + timedelta(minutes=2),
    )
    await db.commit()

    assert cpu.incident_id == disk.incident_id
    incident = await db.get(Incident, cpu.incident_id)
    assert incident.alert_count == 2
    assert incident.severity == "critical"  # max of members
    assert incident.last_seen > incident.first_seen


async def test_alert_without_group_attrs_gets_solo_incident(db):
    engine = make_engine()
    config = await get_config(db)

    a = await engine.process(db, alert(name="A", labels={"env": "prod"}), config, now=NOW)
    b = await engine.process(
        db,
        alert(name="B", labels={"env": "prod"}),
        config,
        now=NOW + timedelta(minutes=1),
    )
    await db.commit()

    assert a.incident_id != b.incident_id
    assert (await db.get(Incident, a.incident_id)).group_key is None


async def test_resolved_incident_is_never_reattached(db):
    engine = make_engine()
    config = await get_config(db)

    first = await engine.process(db, alert(name="A"), config, now=NOW)
    incident = await db.get(Incident, first.incident_id)
    incident.status = IncidentStatus.resolved
    await db.commit()

    second = await engine.process(db, alert(name="B"), config, now=NOW + timedelta(minutes=1))
    await db.commit()
    assert second.incident_id != first.incident_id


async def test_alert_outside_correlation_window_opens_new_incident(db):
    engine = make_engine()
    config = await get_config(db)

    first = await engine.process(db, alert(name="A"), config, now=NOW)
    late = NOW + timedelta(seconds=config.correlation_window_seconds + 60)
    second = await engine.process(db, alert(name="B"), config, now=late)
    await db.commit()

    assert second.incident_id != first.incident_id
