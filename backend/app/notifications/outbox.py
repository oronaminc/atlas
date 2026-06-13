"""Outbox claim semantics: CAS + lease. Safe at replicas>1; crashed workers'
claims expire and the work is picked up by another pod (at-least-once)."""

from datetime import datetime, timedelta

from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.delivery import Notification


# loose index scan (skip scan): one index probe per distinct tenant via the
# tenant-leading partial claim index, instead of a 230ms full scan + DISTINCT
# at storm scale. NULLS LAST btree default; the trailing UNION recovers the
# NULL-tenant (legacy) group the `> ` walk can't reach.
def _claimable_sql(alias: str = "") -> str:
    p = f"{alias}." if alias else ""
    return (
        f"{p}status IN ('pending','failed') "
        f"AND ({p}retry_at IS NULL OR {p}retry_at <= :now) "
        f"AND ({p}claimed_at IS NULL OR {p}claimed_at < :cutoff)"
    )


# Predicate INLINED into each probe (not a shared CTE) so PG uses the
# tenant-leading partial index per step; a materialized CTE forced a full
# scan (~1s). Inlined loose index scan: ~3ms at 1.3M claimable.
_PG_ACTIVE_TENANTS = f"""
WITH RECURSIVE walk AS (
    (SELECT tenant_id FROM notifications
     WHERE {_claimable_sql()} AND tenant_id IS NOT NULL
     ORDER BY tenant_id LIMIT 1)
    UNION ALL
    SELECT (SELECT n.tenant_id FROM notifications n
            WHERE {_claimable_sql("n")} AND n.tenant_id > walk.tenant_id
            ORDER BY n.tenant_id LIMIT 1)
    FROM walk WHERE walk.tenant_id IS NOT NULL
)
SELECT tenant_id FROM walk WHERE tenant_id IS NOT NULL
UNION ALL
SELECT NULL WHERE EXISTS (
    SELECT 1 FROM notifications WHERE {_claimable_sql()} AND tenant_id IS NULL
)
LIMIT :cap
"""

DEAD_AFTER_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600
DEFAULT_LEASE_SECONDS = 60
MAX_TENANTS_PER_CLAIM = 100  # fan cap for the fairness round-robin

CLAIMABLE_STATUSES = ("pending", "failed")


def _claimable_clause(now: datetime, lease_cutoff: datetime):
    return (
        Notification.status.in_(CLAIMABLE_STATUSES),
        or_(Notification.retry_at.is_(None), Notification.retry_at <= now),
        or_(Notification.claimed_at.is_(None), Notification.claimed_at < lease_cutoff),
    )


def _tenant_eq(tenant_id):
    # NULL-safe equality (legacy rows have tenant_id NULL); PG + SQLite
    if tenant_id is None:
        return Notification.tenant_id.is_(None)
    return Notification.tenant_id == tenant_id


async def _active_tenants(db: AsyncSession, claimable, *, now, lease_cutoff) -> list:
    """Distinct tenants with claimable work — the round-robin keys."""
    if db.bind.dialect.name == "postgresql":
        rows = await db.execute(
            text(_PG_ACTIVE_TENANTS),
            {"now": now, "cutoff": lease_cutoff, "cap": MAX_TENANTS_PER_CLAIM},
        )
        return list(rows.scalars())
    # SQLite (tests): tiny data, plain DISTINCT is fine
    rows = await db.execute(
        select(Notification.tenant_id).where(*claimable).distinct().limit(MAX_TENANTS_PER_CLAIM)
    )
    return list(rows.scalars())


async def _claim_for_tenant(
    db: AsyncSession, claimable, tenant_id, *, now, worker_id, limit
) -> list:
    """Claim up to `limit` ids for one tenant, ordered (priority, created_at)
    so critical drains first. CAS each — SKIP LOCKED is the PG throughput
    optimization, the CAS guard is the correctness one."""
    candidates = (
        select(Notification.id)
        .where(*claimable, _tenant_eq(tenant_id))
        .order_by(Notification.priority.asc(), Notification.created_at.asc())
        .limit(limit)
    )
    if db.bind.dialect.name == "postgresql":
        candidates = candidates.with_for_update(skip_locked=True)
    candidate_ids = list((await db.execute(candidates)).scalars())
    claimed = []
    for notification_id in candidate_ids:
        result = await db.execute(
            update(Notification)
            .where(Notification.id == notification_id, *claimable)
            .values(claimed_at=now, claimed_by=worker_id)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            claimed.append(notification_id)
    return claimed


async def claim_batch(
    db: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    limit: int = 50,
) -> list[Notification]:
    """Fair claim: round-robin an equal share of `limit` across every tenant
    with claimable work, so one subsidiary's storm can't starve another.
    Within a tenant, oldest highest-priority first."""
    lease_cutoff = now - timedelta(seconds=lease_seconds)
    claimable = _claimable_clause(now, lease_cutoff)

    tenants = await _active_tenants(db, claimable, now=now, lease_cutoff=lease_cutoff)
    if not tenants:
        return []

    share = max(1, limit // len(tenants))
    claimed_ids: list = []
    refillable: list = []
    # pass 1: equal share per tenant
    for tenant_id in tenants:
        got = await _claim_for_tenant(
            db, claimable, tenant_id, now=now, worker_id=worker_id, limit=share
        )
        claimed_ids.extend(got)
        if len(got) == share:
            refillable.append(tenant_id)  # filled its share, may have more
    # pass 2: hand leftover capacity to tenants that filled their share
    remaining = limit - len(claimed_ids)
    for tenant_id in refillable:
        if remaining <= 0:
            break
        got = await _claim_for_tenant(
            db, claimable, tenant_id, now=now, worker_id=worker_id, limit=remaining
        )
        claimed_ids.extend(got)
        remaining -= len(got)

    if not claimed_ids:
        return []

    res = await db.execute(
        select(Notification)
        .options(joinedload(Notification.incident))
        .where(Notification.id.in_(claimed_ids))
        .order_by(Notification.priority.asc(), Notification.created_at.asc())
        .execution_options(populate_existing=True)
    )
    return list(res.scalars().unique())


async def mark_sent(db: AsyncSession, n: Notification, *, now: datetime) -> None:
    n.status = "sent"
    n.sent_at = now
    n.claimed_at = None
    n.claimed_by = None
    await db.flush()


async def mark_failed(db: AsyncSession, n: Notification, error: str, *, now: datetime) -> None:
    n.attempts += 1
    n.last_error = error[:2000]
    n.claimed_at = None
    n.claimed_by = None
    if n.attempts >= DEAD_AFTER_ATTEMPTS:
        n.status = "dead"
        n.retry_at = None
    else:
        n.status = "failed"
        backoff = min(BACKOFF_BASE_SECONDS * (2 ** (n.attempts - 1)), BACKOFF_CAP_SECONDS)
        n.retry_at = now + timedelta(seconds=backoff)
    await db.flush()


async def defer(
    db: AsyncSession, n: Notification, *, retry_at: datetime, reason: str | None = None
) -> None:
    """Quota hit: release the claim and try again after the window resets.
    `reason` is surfaced in last_error so the /ops delivery panel shows WHY a
    row is stuck (status stays claimable)."""
    n.retry_at = retry_at
    n.claimed_at = None
    n.claimed_by = None
    if reason is not None:
        n.last_error = reason[:2000]
    await db.flush()
