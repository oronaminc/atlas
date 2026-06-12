"""Outbox claim semantics: CAS + lease. Safe at replicas>1; crashed workers'
claims expire and the work is picked up by another pod (at-least-once)."""

from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.delivery import Notification

DEAD_AFTER_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600
DEFAULT_LEASE_SECONDS = 60

CLAIMABLE_STATUSES = ("pending", "failed")


def _claimable_clause(now: datetime, lease_cutoff: datetime):
    return (
        Notification.status.in_(CLAIMABLE_STATUSES),
        or_(Notification.retry_at.is_(None), Notification.retry_at <= now),
        or_(Notification.claimed_at.is_(None), Notification.claimed_at < lease_cutoff),
    )


async def claim_batch(
    db: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    limit: int = 50,
) -> list[Notification]:
    lease_cutoff = now - timedelta(seconds=lease_seconds)

    candidates = select(Notification.id).where(*_claimable_clause(now, lease_cutoff))
    candidates = candidates.order_by(Notification.created_at.asc()).limit(limit)
    if db.bind.dialect.name == "postgresql":
        candidates = candidates.with_for_update(skip_locked=True)
    candidate_ids = list((await db.execute(candidates)).scalars())
    if not candidate_ids:
        return []

    claimed_ids = []
    for notification_id in candidate_ids:
        # CAS: only one worker's UPDATE matches; SKIP LOCKED above is a
        # throughput optimization on PG, this guard is the correctness one.
        result = await db.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                *_claimable_clause(now, lease_cutoff),
            )
            .values(claimed_at=now, claimed_by=worker_id)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            claimed_ids.append(notification_id)
    if not claimed_ids:
        return []

    res = await db.execute(
        select(Notification)
        .options(joinedload(Notification.incident))
        .where(Notification.id.in_(claimed_ids))
        .order_by(Notification.created_at.asc())
        .execution_options(populate_existing=True)
    )
    return list(res.scalars().unique())


async def mark_sent(db: AsyncSession, n: Notification, *, now: datetime) -> None:
    n.status = "sent"
    n.sent_at = now
    n.claimed_at = None
    n.claimed_by = None
    await db.flush()


async def mark_failed(
    db: AsyncSession, n: Notification, error: str, *, now: datetime
) -> None:
    n.attempts += 1
    n.last_error = error[:2000]
    n.claimed_at = None
    n.claimed_by = None
    if n.attempts >= DEAD_AFTER_ATTEMPTS:
        n.status = "dead"
        n.retry_at = None
    else:
        n.status = "failed"
        backoff = min(
            BACKOFF_BASE_SECONDS * (2 ** (n.attempts - 1)), BACKOFF_CAP_SECONDS
        )
        n.retry_at = now + timedelta(seconds=backoff)
    await db.flush()


async def defer(db: AsyncSession, n: Notification, *, retry_at: datetime) -> None:
    """Quota hit: release the claim and try again after the window resets."""
    n.retry_at = retry_at
    n.claimed_at = None
    n.claimed_by = None
    await db.flush()
