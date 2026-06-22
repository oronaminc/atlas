"""Real-PG: threshold filter under concurrent correlation workers. Below-
threshold events are suppressed exactly once (terminal, no re-claim, no
incident); above-threshold create incidents. Mock Mimir (fail-open path is
unit-tested separately)."""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base
from app.models.alerting import AlertEvent
from app.models.threshold import RuleCatalog, ThresholdOverride
from app.services.correlation.dedup import InMemoryDedupStore
from app.services.grouping_config import get_active_rule
from app.services.incident_service import group_alert
from app.services.threshold import ValueCache, should_suppress
from app.workers.correlation_worker import claim_events
from tests.notifications.helpers import NOW

PG_URL = os.environ.get("ATLAS_PG_TEST_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="ATLAS_PG_TEST_URL not set")
N_WORKERS = 4


@pytest_asyncio.fixture
async def pg_factory():
    schema = f"thr_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(
        PG_URL, connect_args={"server_settings": {"search_path": schema}}, pool_size=N_WORKERS + 2
    )
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


async def _fetch(promql):  # LOW -> 92 (suppress), HIGH -> 97 (pass)
    return 92.0 if '"LOW"' in promql else 97.0


async def test_concurrent_threshold_filter(pg_factory):
    async with pg_factory() as db:
        db.add(RuleCatalog(alertname="A", comparator=">", value_query='m{cmdb_ci="{{cmdb_ci}}"}'))
        db.add(ThresholdOverride(alertname="A", target_cmdb_ci="LOW", value=95))
        db.add(ThresholdOverride(alertname="A", target_cmdb_ci="HIGH", value=95))
        for i in range(6):
            db.add(
                AlertEvent(
                    fingerprint=f"low{i}",
                    source="am",
                    name="A",
                    severity="critical",
                    status="firing",
                    labels={"cmdb_ci": "LOW", "host": f"l{i}"},
                    annotations={},
                    starts_at=NOW,
                    received_at=NOW,
                )
            )
        for i in range(6):
            db.add(
                AlertEvent(
                    fingerprint=f"high{i}",
                    source="am",
                    name="A",
                    severity="critical",
                    status="firing",
                    labels={"cmdb_ci": "HIGH", "host": f"h{i}"},
                    annotations={},
                    starts_at=NOW,
                    received_at=NOW,
                    cmdb_service_l2_code=f"HIGH-{i}",
                )
            )
        await db.commit()

    async def worker():
        async with pg_factory() as db:
            InMemoryDedupStore()  # dedup not exercised (distinct fingerprints)
            cache = ValueCache()
            rule = await get_active_rule(db)
            while True:
                events = await claim_events(
                    db, worker_id=f"w{uuid.uuid4().hex[:4]}", now=NOW, limit=3
                )
                if not events:
                    break
                for event in events:
                    suppress, value = await should_suppress(
                        db, event, fetch_value=_fetch, cache=cache
                    )
                    if value is not None:
                        event.value = value
                    if suppress:
                        event.suppressed = True
                        continue
                    await group_alert(db, event, rule, NOW)
                    event.correlated = True
                await db.commit()

    await asyncio.gather(*[worker() for _ in range(N_WORKERS)])

    async with pg_factory() as db:
        suppressed = (
            await db.execute(
                select(func.count()).select_from(AlertEvent).where(AlertEvent.suppressed.is_(True))
            )
        ).scalar_one()
        with_incident = (
            await db.execute(
                select(func.count())
                .select_from(AlertEvent)
                .where(AlertEvent.incident_id.isnot(None))
            )
        ).scalar_one()
        assert suppressed == 6  # all LOW suppressed, exactly once
        assert with_incident == 6  # all HIGH escalated
        # no event both suppressed and attached
        both = (
            await db.execute(
                select(func.count())
                .select_from(AlertEvent)
                .where(AlertEvent.suppressed.is_(True), AlertEvent.incident_id.isnot(None))
            )
        ).scalar_one()
        assert both == 0
