"""Global search (Feature B). Tenancy-scoped automatically: AlertEvent and
Incident are TenantScoped, so the choke point filters a service user to its
own rows; HQ (tenant_id NULL scope) sees all.

Types:
  host  -> incidents.group_key match (small table) -> link to /graph
  label -> alert_events.labels @> {k:v}, TIME-BOUNDED (partition pruning) +
           GIN index (jsonb_path_ops) -> link to incident
  text  -> incidents.title ILIKE -> link to /ops detail

Never an unbounded scan on the partitioned alert_events: label search always
carries received_at >= now-since (default 7d, max 30d).
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.alerting import AlertEvent, Incident
from app.models.base import utcnow

router = APIRouter(prefix="/search", tags=["search"])

DEFAULT_SINCE_DAYS = 7
MAX_SINCE_DAYS = 30


def _label_match(db: AsyncSession, key: str, value: str):
    """Portable labels[key]==value: PG uses jsonb @> (GIN-indexed), SQLite
    uses json_extract (tests only)."""
    if db.bind.dialect.name == "postgresql":
        return AlertEvent.labels.op("@>")({key: value})
    return func.json_extract(AlertEvent.labels, f"$.{key}") == value


@router.get("")
async def search(
    q: str = Query(min_length=1, max_length=200),
    type: str = Query(default="host", pattern="^(host|label|text)$"),
    since: int = Query(default=DEFAULT_SINCE_DAYS, ge=1, le=MAX_SINCE_DAYS),
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if type == "host":
        rows = (
            await db.execute(
                select(
                    Incident.group_key,
                    func.count().label("incidents"),
                    func.max(Incident.last_seen).label("last_seen"),
                )
                .where(Incident.group_key.is_not(None), Incident.group_key.ilike(f"%{q}%"))
                .group_by(Incident.group_key)
                .order_by(func.max(Incident.last_seen).desc())
                .limit(limit)
            )
        ).all()
        return envelope(
            {
                "type": "host",
                "results": [
                    {
                        "host": gk,
                        "incidents": n,
                        "last_seen": ls.isoformat() if ls else None,
                    }
                    for gk, n, ls in rows
                ],
            }
        )

    if type == "label":
        if "=" not in q:
            return envelope({"type": "label", "results": [], "error": "use key=value"})
        key, value = q.split("=", 1)
        cutoff = utcnow() - timedelta(days=since)
        rows = (
            await db.execute(
                select(AlertEvent)
                .where(
                    AlertEvent.received_at >= cutoff,  # partition pruning
                    _label_match(db, key.strip(), value.strip()),
                )
                .order_by(AlertEvent.received_at.desc())
                .limit(limit)
            )
        ).scalars()
        return envelope(
            {
                "type": "label",
                "results": [
                    {
                        "alert_event_id": str(a.id),
                        "name": a.name,
                        "severity": a.severity,
                        "incident_id": str(a.incident_id) if a.incident_id else None,
                        "labels": a.labels,
                        "received_at": a.received_at.isoformat(),
                    }
                    for a in rows
                ],
            }
        )

    # type == "text"
    rows = (
        await db.execute(
            select(Incident)
            .where(Incident.title.ilike(f"%{q}%"))
            .order_by(Incident.last_seen.desc())
            .limit(limit)
        )
    ).scalars()
    return envelope(
        {
            "type": "text",
            "results": [
                {
                    "incident_id": str(i.id),
                    "title": i.title,
                    "severity": i.severity,
                    "status": i.status.value,
                    "group_key": i.group_key,
                    "last_seen": i.last_seen.isoformat(),
                }
                for i in rows
            ],
        }
    )
