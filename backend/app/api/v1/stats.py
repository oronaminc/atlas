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

router = APIRouter(prefix="/stats", tags=["stats"])

SEVERITIES = ("critical", "warning", "info")
NOTIFICATION_STATUSES = ("pending", "sent", "failed", "dead")
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


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
                .where(Incident.status != IncidentStatus.resolved)
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
    alerts_24h = (
        await db.execute(
            select(func.count())
            .select_from(AlertEvent)
            .where(AlertEvent.received_at > utcnow() - timedelta(hours=24))
        )
    ).scalar_one()

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
    Bucketing in Python for SQLite/PG portability; windows are small."""
    now = utcnow()
    since = now - timedelta(hours=hours)
    bucket_seconds = 3600 if hours <= 48 else 86400

    rows = (
        await db.execute(
            select(AlertEvent.received_at, AlertEvent.severity).where(
                AlertEvent.received_at > since
            )
        )
    ).all()

    n_buckets = max((hours * 3600) // bucket_seconds, 1)
    buckets: list[dict] = [
        {
            "bucket": (since + timedelta(seconds=i * bucket_seconds)).isoformat(),
            **{s: 0 for s in SEVERITIES},
        }
        for i in range(n_buckets)
    ]

    for received_at, severity in rows:
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        index = int((received_at - since).total_seconds() // bucket_seconds)
        if 0 <= index < n_buckets and severity in SEVERITIES:
            buckets[index][severity] += 1

    return envelope({"bucket_seconds": bucket_seconds, "buckets": buckets})


@router.get("/hosts")
async def hosts(
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
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
        if status != IncidentStatus.resolved:
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
