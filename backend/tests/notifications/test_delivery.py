"""Delivery loop: send via the per-group channel, retry on failure, quota defer
(env limits), throttle, missing-channel."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.delivery import Notification
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending
from tests.notifications.helpers import (
    NOW,
    FakeChannel,
    FakeThrottle,
    seed_group,
    seed_group_channel,
    seed_incident,
    seed_route,
)

pytestmark = pytest.mark.asyncio


async def seed_pending(db, n_chats: int = 1):
    group = await seed_group(db, "oncall", [])
    await seed_route(db, group)
    for i in range(n_chats):
        await seed_group_channel(db, group, "telegram", bot_token="bot", chat_id=f"{i}00")
    incident = await seed_incident(db, channels=["telegram"])
    await fan_out_pending(db, now=NOW)
    await db.commit()
    return incident, group


async def all_rows(db):
    return list((await db.execute(select(Notification))).scalars())


async def test_successful_delivery_marks_sent_and_renders_incident(db):
    incident, _ = await seed_pending(db)
    channel = FakeChannel()
    sent = await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=NOW)
    await db.commit()
    assert sent == 1
    address, text = channel.sent[0]
    assert address == "000" and incident.title in text and "critical" in text
    [row] = await all_rows(db)
    assert row.status == "sent"


async def test_channel_failure_schedules_retry_then_succeeds(db):
    await seed_pending(db)
    channel = FakeChannel(fail_times=1)
    await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=NOW)
    await db.commit()
    [row] = await all_rows(db)
    assert row.status == "failed" and row.attempts == 1 and channel.sent == []
    await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=row.retry_at)
    await db.commit()
    assert row.status == "sent" and len(channel.sent) == 1


async def test_group_hourly_quota_defers_excess(db, monkeypatch):
    monkeypatch.setattr(settings, "NOTIFY_QUOTA_GROUP_PER_HOUR", 2)
    await seed_pending(db, n_chats=3)
    channel = FakeChannel()
    sent = await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=NOW)
    await db.commit()
    assert sent == 2
    deferred = [n for n in await all_rows(db) if n.status == "pending"]
    assert len(deferred) == 1 and deferred[0].retry_at is not None
    later = await deliver_once(
        db, channels={"telegram": channel}, worker_id="w", now=NOW + timedelta(hours=1, minutes=1)
    )
    assert later == 1


async def test_global_daily_quota_defers(db, monkeypatch):
    monkeypatch.setattr(settings, "NOTIFY_QUOTA_GLOBAL_PER_DAY", 1)
    await seed_pending(db, n_chats=2)
    channel = FakeChannel()
    sent = await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=NOW)
    await db.commit()
    assert sent == 1
    assert len([n for n in await all_rows(db) if n.status == "pending"]) == 1


async def test_throttle_acquired_per_send(db):
    await seed_pending(db, n_chats=2)
    channel = FakeChannel()
    throttle = FakeThrottle()
    await deliver_once(
        db, channels={"telegram": channel}, worker_id="w", now=NOW, throttle=throttle
    )
    assert sorted(throttle.acquired) == ["000", "100"]


async def test_missing_channel_fails_row_without_crash(db):
    await seed_pending(db)
    sent = await deliver_once(db, channels={}, worker_id="w", now=NOW)  # no telegram channel
    await db.commit()
    assert sent == 0
    [row] = await all_rows(db)
    assert row.status == "failed"


def test_token_bucket_throttles_at_rate():
    import asyncio

    from app.notifications.throttle import TokenBucket

    clock = {"t": 0.0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float):
        sleeps.append(seconds)
        clock["t"] += seconds

    bucket = TokenBucket(rate_per_second=2, clock=lambda: clock["t"], sleeper=fake_sleep)

    async def run():
        await bucket.acquire("x")
        await bucket.acquire("x")
        await bucket.acquire("x")  # must wait ~0.5s

    asyncio.run(run())
    assert sum(sleeps) > 0
