"""Real-PG: mute + concurrent fan-out together. Two notification workers race
the same incidents; muted incidents produce ZERO notifications, unmuted ones
exactly-once (no double-send), under SKIP LOCKED + notified_at CAS."""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base
from app.models.delivery import Notification, NotificationMute
from app.notifications.fanout import fan_out_pending
from tests.notifications.helpers import (
    NOW,
    seed_group,
    seed_incident_with_events,
    seed_route,
    seed_user,
)

PG_URL = os.environ.get("ATLAS_PG_TEST_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="ATLAS_PG_TEST_URL not set")

N_WORKERS = 4


@pytest_asyncio.fixture
async def pg_factory():
    schema = f"mute_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(
        PG_URL,
        connect_args={"server_settings": {"search_path": schema}},
        pool_size=N_WORKERS + 2,
    )
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


async def test_concurrent_fanout_respects_mute(pg_factory):
    async with pg_factory() as db:
        users = [await seed_user(db, f"u{i}@x.com", chat_id=str(i)) for i in range(3)]
        group = await seed_group(db, "oncall", users)
        await seed_route(db, group, min_severity="warning", channels=["telegram"])
        # 5 unmuted + 5 muted incidents
        for _ in range(5):
            await seed_incident_with_events(db, [("LIVE", "HostHighCPU")])
        for _ in range(5):
            await seed_incident_with_events(db, [("MUTED", "HostOutOfMemory")])
        db.add(
            NotificationMute(
                target_type="server", target_cmdb_ci="MUTED", alertname="HostOutOfMemory"
            )
        )
        await db.commit()

    async def worker():
        async with pg_factory() as db:
            total = 0
            while True:
                n = await fan_out_pending(db, now=NOW)
                await db.commit()
                if n == 0:
                    break
                total += n
            return total

    await asyncio.gather(*[worker() for _ in range(N_WORKERS)])

    async with pg_factory() as db:
        rows = list((await db.execute(select(Notification))).scalars())
        # 5 unmuted incidents x 3 telegram members = 15; muted = 0
        assert len(rows) == 15, len(rows)
        # no double-send: unique (incident, recipient)
        assert len({(r.incident_id, r.recipient_user_id) for r in rows}) == 15
        muted_addr = await db.execute(select(func.count()).select_from(Notification))
        assert muted_addr.scalar_one() == 15
