"""Read-only dashboard aggregations. Any authenticated user."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import apply_tenant_param
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
    _: User = Depends(apply_tenant_param),
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
    _: User = Depends(apply_tenant_param),
):
    """Alert volume by severity: hourly buckets up to 48h, daily beyond.
    Reads pre-aggregated alert_stats_hourly for closed hours + a live scan
    of the un-rolled-up tail only (Phase 3: was a full 24h alert_events
    fetch — 810ms p50 @ 357k rows in Phase 1)."""
    now = utcnow()
    since = now - timedelta(hours=hours)
    bucket_seconds = 3600 if hours <= 48 else 86400

    n_buckets = max((hours * 3600) // bucket_seconds, 1)
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
    db: AsyncSession = Depends(get_db),
    _: User = Depends(apply_tenant_param),
):
    """Incidents grouped by group_key (host=...) — which servers are noisy.
    Folded in Python for SQLite/PG portability."""
    incidents = (
        await db.execute(
            select(
                Incident.group_key,
                Incident.status,
                Incident.severity,
                Incident.last_seen,
                Incident.alert_count,
            ).where(Incident.group_key.is_not(None))
        )
    ).all()

    by_key: dict[str, dict] = {}
    for group_key, status, severity, last_seen, alert_count in incidents:
        entry = by_key.setdefault(
            group_key,
            {
                "group_key": group_key,
                "open": 0,
                "total": 0,
                "alerts": 0,
                "max_severity": "info",
                "last_seen": None,
            },
        )
        entry["total"] += 1
        entry["alerts"] += alert_count
        if status not in (IncidentStatus.resolved, IncidentStatus.suppressed):
            entry["open"] += 1
            if SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK[entry["max_severity"]]:
                entry["max_severity"] = severity
        if entry["last_seen"] is None or (last_seen and last_seen > entry["last_seen"]):
            entry["last_seen"] = last_seen

    result = sorted(by_key.values(), key=lambda e: (-e["open"], -e["alerts"]))[:limit]
    for entry in result:
        if isinstance(entry["last_seen"], datetime):
            entry["last_seen"] = entry["last_seen"].isoformat()
    return envelope(result)
