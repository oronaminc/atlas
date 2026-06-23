"""Outbox claim semantics: CAS + lease, backoff, dead-lettering."""

from datetime import timedelta

from app.models.delivery import Notification
from app.notifications.outbox import (
    DEAD_AFTER_ATTEMPTS,
    claim_batch,
    mark_failed,
    mark_sent,
)
from tests.notifications.helpers import (
    NOW,
    seed_group,
    seed_group_channel,
    seed_incident,
    seed_route,
)


async def seed_notifications(db, n: int = 3) -> list[Notification]:
    group = await seed_group(db, "oncall", [])
    await seed_route(db, group)
    for i in range(n):
        await seed_group_channel(db, group, "telegram", bot_token="b", chat_id=str(i))
    await seed_incident(db, channels=["telegram"])
    from app.notifications.fanout import fan_out_pending

    await fan_out_pending(db, now=NOW)
    await db.commit()
    from sqlalchemy import select

    return list((await db.execute(select(Notification))).scalars())


async def test_claim_is_exclusive_between_workers(db):
    await seed_notifications(db, n=4)

    a = await claim_batch(db, worker_id="w-a", now=NOW, limit=2)
    b = await claim_batch(db, worker_id="w-b", now=NOW, limit=10)
    await db.commit()

    assert len(a) == 2
    assert len(b) == 2  # only the unclaimed remainder
    assert {n.id for n in a}.isdisjoint({n.id for n in b})


async def test_claim_skips_within_lease_but_reclaims_after_expiry(db):
    await seed_notifications(db, n=1)

    first = await claim_batch(db, worker_id="w-a", now=NOW, lease_seconds=60)
    assert len(first) == 1
    await db.commit()

    # within lease: nothing claimable
    assert await claim_batch(db, worker_id="w-b", now=NOW + timedelta(seconds=30)) == []
    # after lease expiry (w-a crashed): reclaimable
    reclaimed = await claim_batch(db, worker_id="w-b", now=NOW + timedelta(seconds=61))
    assert len(reclaimed) == 1
    assert reclaimed[0].claimed_by == "w-b"


async def test_mark_sent_finalizes(db):
    (n,) = await seed_notifications(db, n=1)
    [n] = await claim_batch(db, worker_id="w", now=NOW)
    await mark_sent(db, n, now=NOW)
    await db.commit()

    assert n.status == "sent"
    assert n.sent_at == NOW
    # sent rows are never reclaimed
    assert await claim_batch(db, worker_id="w2", now=NOW + timedelta(hours=2)) == []


async def test_mark_failed_backoff_then_dead(db):
    (n,) = await seed_notifications(db, n=1)
    [n] = await claim_batch(db, worker_id="w", now=NOW)

    await mark_failed(db, n, "boom", now=NOW)
    assert n.status == "failed"
    assert n.attempts == 1
    assert n.last_error == "boom"
    first_retry = n.retry_at
    assert first_retry > NOW

    # not claimable before retry_at
    assert await claim_batch(db, worker_id="w", now=NOW) == []
    # claimable at retry_at; exponential growth
    [n] = await claim_batch(db, worker_id="w", now=first_retry)
    await mark_failed(db, n, "boom2", now=first_retry)
    assert n.attempts == 2
    assert (n.retry_at - first_retry) > (first_retry - NOW)

    # exhaust to dead
    current = n.retry_at
    while n.attempts < DEAD_AFTER_ATTEMPTS:
        [n] = await claim_batch(db, worker_id="w", now=current)
        await mark_failed(db, n, "boom", now=current)
        current = n.retry_at or current + timedelta(hours=2)
    assert n.status == "dead"
    assert await claim_batch(db, worker_id="w", now=current + timedelta(hours=24)) == []
