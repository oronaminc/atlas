"""Real-PG: IMP topology engine under concurrent workers.

Proves the advisory-lock formation + retro-attach are split-brain-safe:
N warnings on one l2 collapse into exactly ONE incident (no double-attach), a
lone critical forms immediately, and a lone warning stays free."""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base
from app.models.alerting import AlertEvent, Incident
from app.services.correlation.dedup import InMemoryDedupStore
from app.services.grouping_config import get_active_rule
from app.services.incident_service import group_alert
from app.workers.correlation_worker import claim_events
from tests.notifications.helpers import NOW

PG_URL = os.environ.get("ATLAS_PG_TEST_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="ATLAS_PG_TEST_URL not set")
N_WORKERS = 4


@pytest_asyncio.fixture
async def pg_factory():
    schema = f"imp_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(
        PG_URL, connect_args={"server_settings": {"search_path": schema}}, pool_size=N_WORKERS + 2
    )
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


def _alert(sev, l2, i):
    return AlertEvent(
        fingerprint=f"{sev}-{l2}-{i}",
        source="alertmanager",
        name="HostHighCpuLoad",
        severity=sev,
        status="firing",
        labels={"cmdb_service_l2_code": l2, "cmdb_service_l2": "svc"},
        annotations={},
        starts_at=NOW,
        received_at=NOW,
        cmdb_service_l2_code=l2,
    )


async def _seed(factory, alerts):
    async with factory() as db:
        db.add_all(alerts)
        await db.commit()


async def _worker(factory):
    async with factory() as db:
        rule = await get_active_rule(db)
        dedup = InMemoryDedupStore()
        while True:
            claimed = await claim_events(db, worker_id=f"w{uuid.uuid4().hex[:4]}", now=NOW, limit=3)
            if not claimed:
                break
            for ev in claimed:
                if ev.incident_id is not None:
                    ev.correlated = True
                    continue
                key = ev.fingerprint
                if await dedup.seen_within(key, rule.dedup_window_seconds):
                    pass  # distinct fingerprints here; dedup not exercised
                await group_alert(db, ev, rule, NOW)
                ev.correlated = True
            await db.commit()


async def _run(factory):
    await asyncio.gather(*[_worker(factory) for _ in range(N_WORKERS)])


async def test_split_brain_warnings_one_incident(pg_factory):
    # 6 warnings on the SAME l2 -> exactly one incident with all 6, no double-attach
    await _seed(pg_factory, [_alert("warning", "L2A", i) for i in range(6)])
    await _run(pg_factory)
    async with pg_factory() as db:
        n_inc = (await db.execute(select(func.count()).select_from(Incident))).scalar_one()
        attached = (
            await db.execute(
                select(func.count())
                .select_from(AlertEvent)
                .where(AlertEvent.incident_id.isnot(None))
            )
        ).scalar_one()
        inc = (await db.execute(select(Incident))).scalars().first()
        assert n_inc == 1, f"split-brain: {n_inc} incidents"
        assert attached == 6
        assert inc.alert_count == 6  # no double-count under concurrency


async def test_criticals_distinct_l2_form_each(pg_factory):
    # 6 criticals on DISTINCT l2 -> 6 incidents, each size 1 (critical-immediate)
    await _seed(pg_factory, [_alert("critical", f"L2-{i}", i) for i in range(6)])
    await _run(pg_factory)
    async with pg_factory() as db:
        n_inc = (await db.execute(select(func.count()).select_from(Incident))).scalar_one()
        assert n_inc == 6
        counts = (await db.execute(select(Incident.alert_count))).scalars().all()
        assert all(c == 1 for c in counts)


async def test_critical_forms_warning_stays_free(pg_factory):
    # one lone critical (own l2) forms; one lone warning (own l2) stays free
    await _seed(pg_factory, [_alert("critical", "CRIT", 0), _alert("warning", "WARN", 0)])
    await _run(pg_factory)
    async with pg_factory() as db:
        incs = (await db.execute(select(Incident))).scalars().all()
        assert len(incs) == 1 and incs[0].cmdb_service_l2_code == "CRIT"
        free = (
            (await db.execute(select(AlertEvent).where(AlertEvent.cmdb_service_l2_code == "WARN")))
            .scalars()
            .one()
        )
        assert free.incident_id is None and free.correlated is True
