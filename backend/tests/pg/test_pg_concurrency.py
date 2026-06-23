"""True-race concurrency tests against real PostgreSQL.

Skipped unless ATLAS_PG_TEST_URL is set (e.g. via scripts/pg-concurrency-test.sh,
which boots PG through docker compose).

What this DOES prove:
- N concurrent workers (asyncio tasks, each with its OWN PG connection) racing
  on the same outbox: FOR UPDATE SKIP LOCKED + CAS claims -> every notification
  sent exactly once, in-flight rows protected by the lease.
- N concurrent correlation workers racing on events sharing a group_key:
  claim exclusivity + pg_advisory_xact_lock -> exactly ONE incident.

What this does NOT prove:
- Separate OS processes / pods (concurrency here is one event loop scheduling
  genuinely parallel PG transactions over distinct connections; PG-side locking
  behaves identically, client-side GIL effects are not exercised).
- kill -9 mid-transaction (covered logically by lease-expiry tests; PG aborts
  the tx and releases row locks, which is strictly safer than the simulated case).
- Network partitions / split brain.
"""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base
from app.models.alerting import AlertEvent, Incident
from app.models.delivery import Notification
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending
from tests.notifications.helpers import (
    NOW,
    seed_group,
    seed_group_channel,
    seed_incident,
    seed_route,
)

PG_URL = os.environ.get("ATLAS_PG_TEST_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="ATLAS_PG_TEST_URL not set (run scripts/pg-concurrency-test.sh)"
)

N_WORKERS = 4


@pytest_asyncio.fixture
async def pg_factory():
    # isolated schema per run
    schema = f"concurrency_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(
        PG_URL,
        connect_args={"server_settings": {"search_path": schema}},
        pool_size=N_WORKERS + 2,
    )
    async with engine.begin() as conn:
        from sqlalchemy import text

        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as conn:
        from sqlalchemy import text

        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


async def test_pg_concurrent_workers_send_exactly_once(pg_factory, monkeypatch):
    # Quota out of scope (exactly-once-under-concurrency, not the cap): lift the
    # env group/day quotas so all 40 send.
    from app.core.config import settings

    monkeypatch.setattr(settings, "NOTIFY_QUOTA_GROUP_PER_HOUR", 10_000)
    monkeypatch.setattr(settings, "NOTIFY_QUOTA_GLOBAL_PER_DAY", 10_000)
    n_targets = 40
    async with pg_factory() as db:
        group = await seed_group(db, "oncall", [])
        await seed_route(db, group)
        for i in range(n_targets):  # the group's own 40 telegram chats
            await seed_group_channel(db, group, "telegram", bot_token="b", chat_id=f"{i}")
        await seed_incident(db, channels=["telegram"])
        await fan_out_pending(db, now=NOW)
        await db.commit()

    sent_log: list[str] = []  # shared across workers

    class CountingChannel:
        async def send(self, address: str, text: str) -> None:
            sent_log.append(address)
            await asyncio.sleep(0)  # force interleaving mid-delivery

    async def worker(worker_id: str):
        async with pg_factory() as db:
            total = 0
            while True:
                sent = await deliver_once(
                    db,
                    channels={"telegram": CountingChannel()},
                    worker_id=worker_id,
                    now=NOW,
                    limit=5,
                )
                await db.commit()
                if sent == 0:
                    break
                total += sent
            return total

    totals = await asyncio.gather(*[worker(f"pod-{i}") for i in range(N_WORKERS)])

    assert len(sent_log) == n_targets, f"expected {n_targets} sends, got {len(sent_log)}"
    assert len(set(sent_log)) == n_targets, "DOUBLE SEND detected"
    assert sum(totals) == n_targets

    async with pg_factory() as db:
        statuses = (await db.execute(select(Notification.status))).scalars().all()
        assert all(s == "sent" for s in statuses)


async def test_pg_concurrent_correlation_single_incident(pg_factory):
    from app.services.correlation.engine import build_event
    from app.services.grouping_config import get_active_rule
    from app.services.incident_service import group_alert
    from app.workers.correlation_worker import claim_events
    from tests.correlation.helpers import alert

    n_events = 20
    l2_labels = {"host": "web-01", "cmdb_service_l2_code": "L2X"}
    async with pg_factory() as db:
        for i in range(n_events):
            # distinct names (no dedup) sharing l2 topology key -> one incident
            db.add(build_event(alert(name=f"Alert{i}", labels=l2_labels), received_at=NOW))
        await db.commit()

    async def worker(worker_id: str):
        async with pg_factory() as db:
            rule = await get_active_rule(db)
            processed = 0
            while True:
                events = await claim_events(db, worker_id=worker_id, now=NOW, limit=3)
                if not events:
                    break
                for event in events:
                    await group_alert(db, event, rule, NOW)
                    event.correlated = True
                    await asyncio.sleep(0)  # interleave mid-batch
                await db.commit()
                processed += len(events)
            return processed

    totals = await asyncio.gather(*[worker(f"pod-{i}") for i in range(N_WORKERS)])
    # IMP: forming the incident retro-attaches all free in-window siblings via a
    # bulk UPDATE, so most events are absorbed WITHOUT being individually claimed
    # — explicit claims are a subset of n_events. Correctness is the incident
    # invariants below (single incident, every event attached exactly once).
    assert 0 < sum(totals) <= n_events

    async with pg_factory() as db:
        n_incidents = (await db.execute(select(func.count()).select_from(Incident))).scalar_one()
        assert n_incidents == 1, f"split-brain grouping: {n_incidents} incidents"
        incident = (await db.execute(select(Incident))).scalar_one()
        assert incident.alert_count == n_events
        uncorrelated = (
            await db.execute(
                select(func.count()).select_from(AlertEvent).where(AlertEvent.incident_id.is_(None))
            )
        ).scalar_one()
        assert uncorrelated == 0
