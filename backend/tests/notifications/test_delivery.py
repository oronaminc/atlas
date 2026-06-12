"""Delivery loop: send via channel, retry on failure, quota defer, throttle."""

from datetime import timedelta

from sqlalchemy import select

from app.models.delivery import Notification
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending
from app.notifications.settings import get_notification_settings
from tests.notifications.helpers import (
    NOW,
    FakeChannel,
    FakeThrottle,
    seed_group,
    seed_incident,
    seed_route,
    seed_user,
)


async def seed_pending(db, n_users: int = 1, channels: list[str] | None = None):
    users = [await seed_user(db, f"u{i}@example.com", chat_id=f"{i}00") for i in range(n_users)]
    group = await seed_group(db, "oncall", users)
    await seed_route(db, group, channels=channels or ["telegram"])
    incident = await seed_incident(db)
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
    assert address == "000"
    assert incident.title in text
    assert "critical" in text
    [row] = await all_rows(db)
    assert row.status == "sent"


async def test_channel_failure_schedules_retry_then_succeeds(db):
    await seed_pending(db)
    channel = FakeChannel(fail_times=1)

    await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=NOW)
    await db.commit()
    [row] = await all_rows(db)
    assert row.status == "failed"
    assert row.attempts == 1
    assert channel.sent == []

    # retry after backoff succeeds
    await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=row.retry_at)
    await db.commit()
    assert row.status == "sent"
    assert len(channel.sent) == 1


async def test_group_hourly_quota_defers_excess(db):
    await seed_pending(db, n_users=3)
    settings_row = await get_notification_settings(db)
    settings_row.quota_group_per_hour = 2
    await db.commit()

    channel = FakeChannel()
    sent = await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=NOW)
    await db.commit()

    assert sent == 2
    deferred = [n for n in await all_rows(db) if n.status == "pending"]
    assert len(deferred) == 1
    assert deferred[0].retry_at is not None and deferred[0].retry_at > NOW
    # after the window resets, the deferred one goes out
    sent_later = await deliver_once(
        db,
        channels={"telegram": channel},
        worker_id="w",
        now=NOW + timedelta(hours=1, minutes=1),
    )
    assert sent_later == 1


async def test_global_daily_quota_defers(db):
    await seed_pending(db, n_users=2)
    settings_row = await get_notification_settings(db)
    settings_row.quota_global_per_day = 1
    await db.commit()

    channel = FakeChannel()
    sent = await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=NOW)
    await db.commit()

    assert sent == 1
    assert len([n for n in await all_rows(db) if n.status == "pending"]) == 1


async def test_throttle_acquired_per_send(db):
    await seed_pending(db, n_users=2)
    channel = FakeChannel()
    throttle = FakeThrottle()

    await deliver_once(
        db, channels={"telegram": channel}, worker_id="w", now=NOW, throttle=throttle
    )
    assert sorted(throttle.acquired) == ["000", "100"]


async def test_missing_channel_fails_row_without_crash(db):
    await seed_pending(db, channels=["telegram"])
    # no telegram channel configured (e.g. token removed)
    sent = await deliver_once(db, channels={}, worker_id="w", now=NOW)
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
        await bucket.acquire("x")  # burst capacity
        await bucket.acquire("x")
        await bucket.acquire("x")  # must wait ~0.5s

    asyncio.get_event_loop().run_until_complete(run()) if False else asyncio.run(run())
    assert sum(sleeps) > 0
