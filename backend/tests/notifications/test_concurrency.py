"""Multi-replica safety. Two workers on the same DB:
- outbox: no double-send, crash mid-delivery resumes via lease expiry
- correlation: claimed events are exclusive, no duplicate incidents

Uses a file-backed SQLite DB so two independent sessions see committed state.
"""

from datetime import timedelta

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base
from app.models.alerting import AlertEvent, Incident
from app.models.delivery import Notification
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending
from app.notifications.outbox import claim_batch
from tests.notifications.helpers import (
    NOW,
    FakeChannel,
    seed_group,
    seed_incident,
    seed_route,
    seed_user,
)


@pytest_asyncio.fixture
async def file_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/concurrency.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def seed_outbox(factory, n_users: int) -> None:
    async with factory() as db:
        users = [await seed_user(db, f"u{i}@example.com", chat_id=f"{i}00") for i in range(n_users)]
        group = await seed_group(db, "oncall", users)
        await seed_route(db, group)
        await seed_incident(db)
        await fan_out_pending(db, now=NOW)
        await db.commit()


async def test_two_workers_never_double_send(file_db):
    await seed_outbox(file_db, n_users=6)
    channel_a, channel_b = FakeChannel(), FakeChannel()

    # interleaved claim+deliver from two separate sessions (two pods)
    async with file_db() as db_a, file_db() as db_b:
        await deliver_once(db_a, channels={"telegram": channel_a}, worker_id="pod-a", now=NOW)
        await db_a.commit()
        await deliver_once(db_b, channels={"telegram": channel_b}, worker_id="pod-b", now=NOW)
        await db_b.commit()

    sent_addresses = [a for a, _ in channel_a.sent] + [a for a, _ in channel_b.sent]
    assert len(sent_addresses) == 6
    assert len(set(sent_addresses)) == 6  # nothing sent twice

    async with file_db() as db:
        statuses = (await db.execute(select(Notification.status))).scalars().all()
        assert all(s == "sent" for s in statuses)


async def test_crash_mid_delivery_is_resumed_by_other_worker(file_db):
    await seed_outbox(file_db, n_users=1)

    # pod-a claims, then dies before sending (session closed, no mark)
    async with file_db() as db_a:
        claimed = await claim_batch(db_a, worker_id="pod-a", now=NOW, lease_seconds=60)
        assert len(claimed) == 1
        await db_a.commit()  # claim persisted; crash happens after this point

    channel = FakeChannel()
    async with file_db() as db_b:
        # within lease: pod-b must NOT pick it up (no double-send while pod-a may be alive)
        sent = await deliver_once(
            db_b,
            channels={"telegram": channel},
            worker_id="pod-b",
            now=NOW + timedelta(seconds=30),
        )
        assert sent == 0 and channel.sent == []
        # after lease expiry: pod-b resumes the work
        sent = await deliver_once(
            db_b,
            channels={"telegram": channel},
            worker_id="pod-b",
            now=NOW + timedelta(seconds=61),
        )
        await db_b.commit()
        assert sent == 1 and len(channel.sent) == 1


async def test_two_correlation_workers_claim_exclusively_no_duplicate_incident(file_db):
    from app.services.correlation.engine import build_event
    from app.services.grouping_config import get_active_rule
    from app.services.incident_service import group_alert
    from app.workers.correlation_worker import claim_events
    from tests.correlation.helpers import alert

    # two criticals on the SAME l2 (topology key) -> must end in ONE incident
    # (first forms immediately, second attaches to the open incident).
    l2_labels = {"host": "web-01", "cmdb_service_l2_code": "L2X"}
    async with file_db() as db:
        db.add(build_event(alert(name="HighCPU", labels=l2_labels), received_at=NOW))
        db.add(build_event(alert(name="DiskFull", labels=l2_labels), received_at=NOW))
        await db.commit()

    async with file_db() as db_a, file_db() as db_b:
        claimed_a = await claim_events(db_a, worker_id="pod-a", now=NOW, limit=1)
        await db_a.commit()
        claimed_b = await claim_events(db_b, worker_id="pod-b", now=NOW, limit=10)
        await db_b.commit()

        # exclusive claims
        assert len(claimed_a) == 1 and len(claimed_b) == 1
        assert claimed_a[0].id != claimed_b[0].id

        rule_a = await get_active_rule(db_a)
        await group_alert(db_a, claimed_a[0], rule_a, NOW)
        claimed_a[0].correlated = True
        await db_a.commit()

        rule_b = await get_active_rule(db_b)
        await group_alert(db_b, claimed_b[0], rule_b, NOW)
        claimed_b[0].correlated = True
        await db_b.commit()

    async with file_db() as db:
        n_incidents = (await db.execute(select(func.count()).select_from(Incident))).scalar_one()
        assert n_incidents == 1
        events = list((await db.execute(select(AlertEvent))).scalars())
        assert all(e.incident_id is not None for e in events)


async def test_correlation_claim_lease_expires_for_crashed_worker(file_db):
    from app.services.correlation.engine import build_event
    from app.workers.correlation_worker import claim_events
    from tests.correlation.helpers import alert

    async with file_db() as db:
        db.add(build_event(alert(), received_at=NOW))
        await db.commit()

    async with file_db() as db_a:
        assert len(await claim_events(db_a, worker_id="pod-a", now=NOW)) == 1
        await db_a.commit()  # pod-a dies here

    async with file_db() as db_b:
        assert await claim_events(db_b, worker_id="pod-b", now=NOW + timedelta(seconds=30)) == []
        reclaimed = await claim_events(db_b, worker_id="pod-b", now=NOW + timedelta(seconds=61))
        assert len(reclaimed) == 1
