"""Partition + retention + rollup maintenance (Phase 3).

alert_events is PG RANGE-partitioned by received_at, daily, with a DEFAULT
partition so inserts NEVER fail on a missing date. This module owns:
  - ensure_partitions: today..+N days ahead + the DEFAULT partition
  - rehome_default_rows: move stray DEFAULT rows into proper partitions
    (creates them first); DEFAULT row count is a Phase 5 health metric
  - drop_expired_partitions: optional gzip-CSV archive, then DETACH+DROP
  - retention deletes for incidents / notifications / audit (batched)
  - rollup_hourly: idempotent DELETE+INSERT of closed-hour alert counts

Partition ops are PG-only (SQLite tests: no-ops). All SQL here is raw and
deliberately UNSCOPED by tenant — maintenance is cross-tenant; rollup rows
carry tenant_id so dashboard reads stay choke-point-filtered.
"""

import gzip
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.alerting import Incident, IncidentStatus
from app.models.audit import AuditLog
from app.models.base import utcnow
from app.models.delivery import Notification
from app.models.maintenance import AlertStatsHourly, RetentionConfig

logger = logging.getLogger(__name__)

PARTITION_PREFIX = "alert_events_p"  # alert_events_p20260613
DEFAULT_PARTITION = "alert_events_default"
LEGACY_PARTITION = "alert_events_legacy"
PARTITION_RE = re.compile(rf"^{PARTITION_PREFIX}(\d{{8}})$")
DELETE_BATCH = 50_000


async def get_retention_config(db: AsyncSession) -> RetentionConfig:
    row = (await db.execute(select(RetentionConfig).limit(1))).scalar_one_or_none()
    if row is None:
        row = RetentionConfig()
        db.add(row)
        await db.flush()
    return row


def _is_pg(db: AsyncSession) -> bool:
    return db.bind.dialect.name == "postgresql"


def partition_name(day: datetime) -> str:
    return f"{PARTITION_PREFIX}{day:%Y%m%d}"


async def list_partitions(db: AsyncSession) -> list[str]:
    return [name for name, _ in await list_partition_bounds(db)]


async def list_partition_bounds(db: AsyncSession) -> list[tuple[str, str]]:
    """(partition name, partition bound expr) pairs, e.g.
    ("alert_events_legacy", "FOR VALUES FROM (MINVALUE) TO ('2026-06-14 ...')")."""
    rows = await db.execute(
        text(
            "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "JOIN pg_namespace pn ON pn.oid = p.relnamespace "
            "WHERE p.relname = 'alert_events' AND pn.nspname = current_schema() "
            "ORDER BY c.relname"
        )
    )
    return [(name, bound or "") for name, bound in rows.all()]


_BOUND_RE = re.compile(r"FROM \((.+?)\) TO \((.+?)\)")


def _covered_ranges(bounds: list[tuple[str, str]]) -> list[tuple[datetime, datetime]]:
    """Parse existing range partitions into [from, to) datetime pairs
    (MINVALUE -> datetime.min)."""
    ranges = []
    for _name, bound in bounds:
        match = _BOUND_RE.search(bound)
        if not match:
            continue  # DEFAULT partition
        lo_raw, hi_raw = match.group(1), match.group(2)
        lo = (
            datetime.min.replace(tzinfo=UTC)
            if "MINVALUE" in lo_raw
            else datetime.fromisoformat(lo_raw.strip("'")).astimezone(UTC)
        )
        hi = datetime.fromisoformat(hi_raw.strip("'")).astimezone(UTC)
        ranges.append((lo, hi))
    return ranges


def _day_covered(day: datetime, ranges: list[tuple[datetime, datetime]]) -> bool:
    return any(lo <= day and day + timedelta(days=1) <= hi for lo, hi in ranges)


async def ensure_partitions(db: AsyncSession, days_ahead: int = 7) -> int:
    """Create daily partitions for today..today+days_ahead + DEFAULT."""
    if not _is_pg(db):
        return 0
    bounds = await list_partition_bounds(db)
    existing = {name for name, _ in bounds}
    ranges = _covered_ranges(bounds)
    created = 0
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(days_ahead + 1):
        day = today + timedelta(days=offset)
        name = partition_name(day)
        # skip if a partition of that name exists OR the day is already
        # covered by another range (e.g. the legacy monolith up to cutover)
        if name in existing or _day_covered(day, ranges):
            continue
        await db.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF alert_events "
                f"FOR VALUES FROM ('{day:%Y-%m-%d}') TO ('{day + timedelta(days=1):%Y-%m-%d}')"
            )
        )
        created += 1
    if DEFAULT_PARTITION not in existing:
        await db.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {DEFAULT_PARTITION} PARTITION OF alert_events DEFAULT"
            )
        )
        created += 1
    return created


async def default_partition_count(db: AsyncSession) -> int:
    """Rows stranded in DEFAULT — should always be 0 (Phase 5 metric)."""
    if not _is_pg(db):
        return 0
    if DEFAULT_PARTITION not in set(await list_partitions(db)):
        return 0
    return (await db.execute(text(f"SELECT count(*) FROM {DEFAULT_PARTITION}"))).scalar_one()


async def rehome_default_rows(db: AsyncSession) -> int:
    """Move DEFAULT-partition rows into their proper daily partitions.
    Creates the missing partitions first (must DETACH default to add an
    overlapping range), then re-inserts through the parent router."""
    if not _is_pg(db):
        return 0
    count = await default_partition_count(db)
    if count == 0:
        return 0
    days = (
        await db.execute(
            text(f"SELECT DISTINCT date_trunc('day', received_at) FROM {DEFAULT_PARTITION}")
        )
    ).scalars()
    needed = sorted(d for d in days)
    await db.execute(text(f"ALTER TABLE alert_events DETACH PARTITION {DEFAULT_PARTITION}"))
    for day in needed:
        name = partition_name(day)
        await db.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF alert_events "
                f"FOR VALUES FROM ('{day:%Y-%m-%d}') TO ('{day + timedelta(days=1):%Y-%m-%d}')"
            )
        )
    moved = (
        await db.execute(
            text(
                f"WITH moved AS (DELETE FROM {DEFAULT_PARTITION} RETURNING *) "
                "INSERT INTO alert_events SELECT * FROM moved RETURNING 1"
            )
        )
    ).scalars()
    n = len(list(moved))
    await db.execute(text(f"ALTER TABLE alert_events ATTACH PARTITION {DEFAULT_PARTITION} DEFAULT"))
    logger.info("re-homed %d rows from DEFAULT partition", n)
    return n


async def _archive_partition(db: AsyncSession, name: str) -> Path:
    """Stream a partition to gzip CSV via client-side COPY (air-gap: plain
    mounted volume, no superuser COPY TO PROGRAM). Uses a DEDICATED asyncpg
    connection: COPY on the session's adapted connection deadlocks inside
    SQLAlchemy's greenlet bridge."""
    import asyncpg

    archive_dir = Path(settings.ARCHIVE_DIR)
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / f"{name}.csv.gz"
    schema = (await db.execute(text("SELECT current_schema()"))).scalar_one()
    url = db.bind.url
    dsn = f"postgresql://{url.username}:{url.password}@{url.host}:{url.port or 5432}/{url.database}"
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        with gzip.open(target, "wb") as fh:

            async def sink(data: bytes) -> None:
                fh.write(data)  # asyncpg awaits the writer; must return None

            await conn.copy_from_query(
                f'SELECT * FROM "{schema}"."{name}"',  # noqa: S608
                output=sink,
                format="csv",
                header=True,
            )
    finally:
        await conn.close()
    return target


async def drop_expired_partitions(db: AsyncSession, retention_days: int) -> list[str]:
    """DETACH+DROP daily partitions whose entire range is older than the
    cutoff. The legacy monolith partition drops once fully expired."""
    if not _is_pg(db) or retention_days <= 0:
        return []
    cutoff = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=retention_days
    )
    config = await get_retention_config(db)
    dropped: list[str] = []
    for name in await list_partitions(db):
        match = PARTITION_RE.match(name)
        if match:
            day = datetime.strptime(match.group(1), "%Y%m%d").replace(tzinfo=UTC)
            expired = day + timedelta(days=1) <= cutoff
        elif name == LEGACY_PARTITION:
            # legacy upper bound = its newest row
            newest = (
                await db.execute(text(f"SELECT max(received_at) FROM {LEGACY_PARTITION}"))
            ).scalar_one_or_none()
            expired = newest is not None and newest < cutoff
        else:
            continue
        if not expired:
            continue
        if config.archive_enabled and settings.ARCHIVE_DIR:
            path = await _archive_partition(db, name)
            logger.info("archived %s -> %s", name, path)
        await db.execute(text(f"ALTER TABLE alert_events DETACH PARTITION {name}"))
        await db.execute(text(f"DROP TABLE {name}"))
        dropped.append(name)
    return dropped


async def delete_expired_rows(db: AsyncSession, config: RetentionConfig) -> dict[str, int]:
    """Batched retention DELETEs for the non-partitioned tables."""
    now = utcnow()
    deleted: dict[str, int] = {}

    async def batched(stmt_factory) -> int:
        total = 0
        while True:
            result = await db.execute(stmt_factory())
            await db.flush()
            total += result.rowcount
            if result.rowcount < DELETE_BATCH:
                return total

    if config.incidents_days > 0:
        cutoff = now - timedelta(days=config.incidents_days)
        deleted["incidents"] = await batched(
            lambda: delete(Incident).where(
                Incident.id.in_(
                    select(Incident.id)
                    .where(
                        Incident.status.in_([IncidentStatus.resolved, IncidentStatus.suppressed]),
                        Incident.last_seen < cutoff,
                    )
                    .limit(DELETE_BATCH)
                )
            )
        )
    if config.notifications_days > 0:
        cutoff = now - timedelta(days=config.notifications_days)
        deleted["notifications"] = await batched(
            lambda: delete(Notification).where(
                Notification.id.in_(
                    select(Notification.id)
                    .where(
                        Notification.status.in_(["sent", "dead"]),
                        Notification.created_at < cutoff,
                    )
                    .limit(DELETE_BATCH)
                )
            )
        )
    if config.audit_days > 0:
        cutoff = now - timedelta(days=config.audit_days)
        deleted["audit_logs"] = await batched(
            lambda: delete(AuditLog).where(
                AuditLog.id.in_(
                    select(AuditLog.id).where(AuditLog.created_at < cutoff).limit(DELETE_BATCH)
                )
            )
        )
    return deleted


async def rollup_hourly(db: AsyncSession, lookback_hours: int = 26) -> int:
    """Recompute closed-hour buckets in the lookback window (idempotent
    DELETE+INSERT — NULL-tenant-safe on PG and SQLite). The current partial
    hour is intentionally NOT rolled up; stats endpoints live-scan it."""
    now = utcnow()
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    since = current_hour - timedelta(hours=lookback_hours)

    await db.execute(
        delete(AlertStatsHourly).where(
            AlertStatsHourly.bucket_start >= since,
            AlertStatsHourly.bucket_start < current_hour,
        )
    )
    if _is_pg(db):
        bucket_expr = "date_trunc('hour', received_at)"
    else:
        bucket_expr = "strftime('%Y-%m-%d %H:00:00', received_at)"
    rows = (
        await db.execute(
            text(
                f"SELECT {bucket_expr} AS bucket, severity, count(*) AS n "  # noqa: S608
                "FROM alert_events WHERE received_at >= :since AND received_at < :until "
                "GROUP BY bucket, severity"
            ),
            {"since": since, "until": current_hour},
        )
    ).all()
    for bucket, severity, n in rows:
        if isinstance(bucket, str):
            bucket = datetime.strptime(bucket, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        elif bucket.tzinfo is None:
            bucket = bucket.replace(tzinfo=UTC)
        db.add(AlertStatsHourly(bucket_start=bucket, severity=severity, count=n))
    await db.flush()
    return len(rows)


async def run_maintenance(db: AsyncSession, *, days_ahead: int = 7) -> dict:
    """One full pass: partitions ahead, re-home default, retention, rollups."""
    config = await get_retention_config(db)
    summary = {
        "partitions_created": await ensure_partitions(db, days_ahead),
        "rehomed": await rehome_default_rows(db),
        "partitions_dropped": await drop_expired_partitions(db, config.alert_events_days),
        "deleted": await delete_expired_rows(db, config),
        "rollup_rows": await rollup_hourly(db),
        "default_partition_rows": await default_partition_count(db),
    }
    return summary
