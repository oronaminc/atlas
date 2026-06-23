"""Incident swimlane graph (read-only, any auth).

One lane per INCIDENT (its title); inside each lane its member alerts plotted
over time. IMP: the old host-keyed lanes broke once group_key became the l2
service code, so the model is now incident-centric — an incident IS the lane,
its alerts are the pills.
"""

import uuid
from datetime import UTC, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.alerting import AlertEvent, Incident, IncidentStatus
from app.models.base import utcnow

router = APIRouter(prefix="/graph", tags=["graph"])

ALERTS_PER_INCIDENT = 200  # cap pills per lane so dense incidents stay readable


def _aware(dt):
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _alert_node(e: AlertEvent) -> dict:
    return {
        "id": str(e.id),
        "name": e.name,
        "severity": e.severity,
        "status": e.status,
        "received_at": _aware(e.received_at).isoformat(),
        "cmdb_hostname": e.cmdb_hostname,
        "dedup_count": e.dedup_count,
    }


@router.get("")
async def graph(
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    status: str = Query(default="open,acknowledged"),
    max_lanes: int = Query(default=200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    statuses = [IncidentStatus(s.strip()) for s in status.split(",") if s.strip()]
    since = utcnow() - timedelta(hours=window_hours)

    stmt = (
        select(Incident)
        .where(Incident.last_seen >= since, Incident.status.in_(statuses))
        .order_by(Incident.last_seen.desc())
        .limit(max_lanes + 1)
    )
    incidents = list((await db.execute(stmt)).scalars())
    truncated = len(incidents) > max_lanes
    incidents = incidents[:max_lanes]

    incident_ids = [i.id for i in incidents]
    alerts_by_incident: dict[uuid.UUID, list[dict]] = {}
    if incident_ids:
        rows = list(
            (
                await db.execute(
                    select(AlertEvent)
                    .where(AlertEvent.incident_id.in_(incident_ids))
                    .order_by(AlertEvent.received_at.asc())
                )
            ).scalars()
        )
        for e in rows:
            bucket = alerts_by_incident.setdefault(e.incident_id, [])
            if len(bucket) < ALERTS_PER_INCIDENT:
                bucket.append(_alert_node(e))

    lanes = [
        {
            "id": str(inc.id),
            "title": inc.title,
            "severity": inc.severity,
            "status": inc.status.value,
            "alert_count": inc.alert_count,
            "first_seen": _aware(inc.first_seen).isoformat(),
            "last_seen": _aware(inc.last_seen).isoformat(),
            "cmdb_service_l2_code": inc.cmdb_service_l2_code,
            "alerts": alerts_by_incident.get(inc.id, []),
        }
        for inc in incidents
    ]

    return envelope(
        {
            "incidents": lanes,
            "meta": {"truncated": truncated, "total_incidents": len(incidents)},
        }
    )


@router.get("/incident/{incident_id}")
async def expand_incident(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Full member-alert list for one incident (uncapped)."""
    incident = await db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    events = list(
        (
            await db.execute(
                select(AlertEvent)
                .where(AlertEvent.incident_id == incident_id)
                .order_by(AlertEvent.received_at.asc())
            )
        ).scalars()
    )
    return envelope({"alerts": [_alert_node(e) for e in events]})
