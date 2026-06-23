"""Real-PG: per-incident channel toggles + concurrent fan-out together. Two+
notification workers race the same incidents; incidents with a channel toggled
OFF produce ZERO rows for that channel, toggled-ON incidents fan out exactly
once per recipient (no double-send), under FOR UPDATE SKIP LOCKED + the
notified_at CAS.

(Replaces the pre-IMP mute test: the NotificationMute/route model was retired in
the IMP redesign — suppression is now the incident's own notify_* toggles, so
"60 rows" instead of "0 for muted" was the *correct* new behavior. This asserts
the new toggle model under the same concurrency stress.)
"""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base
from app.models.delivery import Notification
from app.notifications.fanout import fan_out_pending
from tests.notifications.helpers import (
    NOW,
    seed_group,
    seed_group_channel,
    seed_incident,
    seed_route,
)

PG_URL = os.environ.get("ATLAS_PG_TEST_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="ATLAS_PG_TEST_URL not set")

N_WORKERS = 4


@pytest_asyncio.fixture
async def pg_factory():
    schema = f"toggle_{uuid.uuid4().hex[:8]}"
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


async def test_concurrent_fanout_respects_toggles(pg_factory):
    async with pg_factory() as db:
        group = await seed_group(db, "oncall", [])
        await seed_route(db, group)  # maps the group to the test l2
        for i in range(3):  # group's own 3 telegram chats
            await seed_group_channel(db, group, "telegram", bot_token="b", chat_id=str(i))
        # 5 telegram-only incidents -> 3 telegram rows each = 15
        for _ in range(5):
            await seed_incident(db, channels=["telegram"], title="LIVE")
        # 5 all-channels-off incidents -> 0 rows (toggle suppression)
        for _ in range(5):
            await seed_incident(db, channels=[], title="SILENCED")
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
        # 5 telegram-on incidents x 3 members = 15; toggled-off incidents = 0
        assert len(rows) == 15, len(rows)
        assert all(r.channel == "telegram" for r in rows), {r.channel for r in rows}
        # exactly-once under the race: unique (incident, recipient_address)
        assert len({(r.incident_id, r.recipient_address) for r in rows}) == 15
