"""Read-only dashboard aggregations. Any authenticated user."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.alerting import AlertEvent, Incident, IncidentStatus
from app.models.base import utcnow
from app.models.delivery import Notification
from app.models.maintenance import AlertStatsHourly

router = APIRouter(prefix="/stats", tags=["stats"])

SEVERITIES = ("critical", "warning", "info")
NOTIFICATION_STATUSES = ("pending", "sent", "failed", "dead")
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


async def _rollup_floor(db: AsyncSession, since: datetime) -> datetime:
    """Hours >= floor must be live-scanned: everything after the last rolled
    bucket (worker downtime degrades latency, never correctness)."""
    last = (
        await db.execute(
            select(func.max(AlertStatsHourly.bucket_start)).where(
                AlertStatsHourly.bucket_start >= since
            )
        )
    ).scalar_one_or_none()
    if last is None:
        return since
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return last + timedelta(hours=1)


async def _alert_counts(
    db: AsyncSession, since: datetime, until: datetime
) -> list[tuple[datetime, str, int]]:
    """(hour_bucket, severity, count) from rollups + live tail. Both legs go
    through the ORM so the tenancy choke point applies."""
    live_from = max(await _rollup_floor(db, since), since)
    out: list[tuple[datetime, str, int]] = []
    # hour-quantized window start: include the boundary bucket so the
    # leading partial hour isn't dropped (24h counts are hour-granular)
    floor_since = since.replace(minute=0, second=0, microsecond=0)
    rows = await db.execute(
        select(
            AlertStatsHourly.bucket_start, AlertStatsHourly.severity, AlertStatsHourly.count
        ).where(
            AlertStatsHourly.bucket_start >= floor_since,
            AlertStatsHourly.bucket_start < live_from,
        )
    )
    for bucket, severity, n in rows.all():
        if bucket.tzinfo is None:
            bucket = bucket.replace(tzinfo=UTC)
        out.append((bucket, severity, n))
    if live_from < until:
        # live tail: received_at bound -> partition pruning to 1-2 partitions
        live = await db.execute(
            select(AlertEvent.received_at, AlertEvent.severity).where(
                AlertEvent.received_at >= live_from, AlertEvent.received_at < until
            )
        )
        for received_at, severity in live.all():
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=UTC)
            bucket = received_at.replace(minute=0, second=0, microsecond=0)
            out.append((bucket, severity, 1))
    return out


@router.get("/overview")
async def overview(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    incident_counts = dict(
        (await db.execute(select(Incident.status, func.count()).group_by(Incident.status))).all()
    )
    open_by_severity = dict(
        (
            await db.execute(
                select(Incident.severity, func.count())
                .where(Incident.status.notin_([IncidentStatus.resolved, IncidentStatus.suppressed]))
                .group_by(Incident.severity)
            )
        ).all()
    )
    notification_counts = dict(
        (
            await db.execute(
                select(Notification.status, func.count()).group_by(Notification.status)
            )
        ).all()
    )
    now = utcnow()
    alerts_24h = sum(n for _, _, n in await _alert_counts(db, now - timedelta(hours=24), now))

    return envelope(
        {
            "incidents": {s.value: incident_counts.get(s, 0) for s in IncidentStatus},
            "open_by_severity": {s: open_by_severity.get(s, 0) for s in SEVERITIES},
            "notifications": {s: notification_counts.get(s, 0) for s in NOTIFICATION_STATUSES},
            "alerts_24h": alerts_24h,
        }
    )


@router.get("/trend")
async def trend(
    hours: int = Query(default=24, ge=1, le=24 * 7),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Alert volume by severity: hourly buckets up to 48h, daily beyond.
    Reads pre-aggregated alert_stats_hourly for closed hours + a live scan
    of the un-rolled-up tail only (Phase 3: was a full 24h alert_events
    fetch — 810ms p50 @ 357k rows in Phase 1)."""
    now = utcnow()
    bucket_seconds = 3600 if hours <= 48 else 86400
    # Align the window start to the bucket boundary (hour or UTC-day) so display
    # buckets line up exactly with the hour-floored data buckets — otherwise an
    # unaligned `since` shifts every count into the wrong bucket and drops the
    # leading partial one (the "values wrong" bug).
    raw_since = now - timedelta(hours=hours)
    if bucket_seconds == 3600:
        since = raw_since.replace(minute=0, second=0, microsecond=0)
    else:
        since = raw_since.replace(hour=0, minute=0, second=0, microsecond=0)

    n_buckets = int((now - since).total_seconds() // bucket_seconds) + 1
    buckets: list[dict] = [
        {
            "bucket": (since + timedelta(seconds=i * bucket_seconds)).isoformat(),
            **{s: 0 for s in SEVERITIES},
        }
        for i in range(n_buckets)
    ]

    for bucket_start, severity, n in await _alert_counts(db, since, now):
        index = int((bucket_start - since).total_seconds() // bucket_seconds)
        if 0 <= index < n_buckets and severity in SEVERITIES:
            buckets[index][severity] += n

    return envelope({"bucket_seconds": bucket_seconds, "buckets": buckets})


@router.get("/hosts")
async def hosts(
    limit: int = Query(default=50, le=200),
    since_hours: int = Query(default=168, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Per-server status, keyed by the alert's cmdb_hostname (IMP: incident
    group_key is now the l2 service code, so the old host parse was empty).
    For each server: alert count, distinct open/total incidents, worst
    severity, last seen. Folded in Python for SQLite/PG portability."""
    since = utcnow() - timedelta(hours=since_hours)
    rows = (
        await db.execute(
            select(
                AlertEvent.cmdb_hostname,
                AlertEvent.severity,
                AlertEvent.received_at,
                AlertEvent.incident_id,
                Incident.status,
            )
            .join(Incident, Incident.id == AlertEvent.incident_id, isouter=True)
            .where(AlertEvent.cmdb_hostname.isnot(None), AlertEvent.received_at >= since)
        )
    ).all()

    by_host: dict[str, dict] = {}
    inc_seen: dict[str, set] = {}
    open_seen: dict[str, set] = {}
    for host, severity, received_at, incident_id, status in rows:
        entry = by_host.setdefault(
            host,
            {
                "host": host,
                "open": 0,
                "total": 0,
                "alerts": 0,
                "max_severity": "info",
                "last_seen": None,
            },
        )
        entry["alerts"] += 1
        if SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK[entry["max_severity"]]:
            entry["max_severity"] = severity
        if entry["last_seen"] is None or (received_at and received_at > entry["last_seen"]):
            entry["last_seen"] = received_at
        if incident_id is not None:
            inc_seen.setdefault(host, set()).add(incident_id)
            if status not in (IncidentStatus.resolved, IncidentStatus.suppressed):
                open_seen.setdefault(host, set()).add(incident_id)

    for host, entry in by_host.items():
        entry["total"] = len(inc_seen.get(host, set()))
        entry["open"] = len(open_seen.get(host, set()))

    result = sorted(by_host.values(), key=lambda e: (-e["open"], -e["alerts"]))[:limit]
    for entry in result:
        if isinstance(entry["last_seen"], datetime):
            entry["last_seen"] = entry["last_seen"].isoformat()
    return envelope(result)
