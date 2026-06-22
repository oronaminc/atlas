"""Graph endpoint for the 3D alert-relationship view (read-only, any auth).

Nodes: incidents (primary) + hosts (anchors from group_key).
Edges: host membership, temporal proximity (within the correlation window),
same dominant alert name across incidents. "llm_similar" edge kind is
reserved for the future LLM strategy — emitted nowhere yet.
"""

import uuid
from collections import Counter
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
from app.services.grouping_config import get_active_rule

router = APIRouter(prefix="/graph", tags=["graph"])

TEMPORAL_EDGES_PER_NODE = 5  # cap fan-out so dense windows stay readable


def _aware(dt):
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


@router.get("")
async def graph(
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    status: str = Query(default="open,acknowledged"),
    max_nodes: int = Query(default=2000, ge=2, le=5000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    statuses = [IncidentStatus(s.strip()) for s in status.split(",") if s.strip()]
    since = utcnow() - timedelta(hours=window_hours)

    stmt = (
        select(Incident)
        .where(Incident.last_seen >= since, Incident.status.in_(statuses))
        .order_by(Incident.last_seen.desc())
        .limit(max_nodes + 1)
    )
    incidents = list((await db.execute(stmt)).scalars())
    truncated = len(incidents) > max_nodes
    incidents = incidents[:max_nodes]

    # dominant alert name per incident (factual, from correlated events)
    incident_ids = [i.id for i in incidents]
    dominant: dict[uuid.UUID, str] = {}
    if incident_ids:
        rows = (
            await db.execute(
                select(AlertEvent.incident_id, AlertEvent.name).where(
                    AlertEvent.incident_id.in_(incident_ids)
                )
            )
        ).all()
        names_by_incident: dict[uuid.UUID, Counter] = {}
        for incident_id, name in rows:
            names_by_incident.setdefault(incident_id, Counter())[name] += 1
        dominant = {
            incident_id: counter.most_common(1)[0][0]
            for incident_id, counter in names_by_incident.items()
        }

    nodes = []
    hosts: set[str] = set()
    for incident in incidents:
        if incident.group_key:
            hosts.add(incident.group_key)
        nodes.append(
            {
                "id": str(incident.id),
                "kind": "incident",
                "label": incident.title,
                "severity": incident.severity,
                "status": incident.status.value,
                "alert_count": incident.alert_count,
                "group_key": incident.group_key,
                "first_seen": _aware(incident.first_seen).isoformat(),
                "last_seen": _aware(incident.last_seen).isoformat(),
                "dominant_name": dominant.get(incident.id),
            }
        )
    nodes.extend(
        {"id": host, "kind": "host", "label": host, "severity": None, "status": None}
        for host in sorted(hosts)
    )

    edges = []
    for incident in incidents:
        if incident.group_key:
            edges.append(
                {
                    "source": str(incident.id),
                    "target": incident.group_key,
                    "kind": "host",
                    "weight": 1.0,
                }
            )

    rule = await get_active_rule(db)
    window = rule.window_seconds
    # temporal proximity + same dominant name (O(n^2) over capped, windowed set)
    temporal_count: dict[uuid.UUID, int] = {}
    for i, a in enumerate(incidents):
        for b in incidents[i + 1 :]:
            gap = abs((_aware(a.first_seen) - _aware(b.first_seen)).total_seconds())
            if gap <= window and (
                temporal_count.get(a.id, 0) < TEMPORAL_EDGES_PER_NODE
                and temporal_count.get(b.id, 0) < TEMPORAL_EDGES_PER_NODE
            ):
                edges.append(
                    {
                        "source": str(a.id),
                        "target": str(b.id),
                        "kind": "temporal",
                        "weight": round(max(0.0, 1 - gap / window), 3),
                    }
                )
                temporal_count[a.id] = temporal_count.get(a.id, 0) + 1
                temporal_count[b.id] = temporal_count.get(b.id, 0) + 1
            name_a, name_b = dominant.get(a.id), dominant.get(b.id)
            if name_a and name_a == name_b and a.group_key != b.group_key:
                edges.append(
                    {
                        "source": str(a.id),
                        "target": str(b.id),
                        "kind": "same_name",
                        "weight": 1.0,
                    }
                )

    return envelope(
        {
            "nodes": nodes,
            "edges": edges,
            "meta": {"truncated": truncated, "total_incidents": len(incidents)},
        }
    )


@router.get("/incident/{incident_id}")
async def expand_incident(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """On-demand expansion: alert-event nodes for one incident."""
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
    nodes = [
        {
            "id": str(e.id),
            "kind": "alert",
            "label": e.name,
            "source": e.source,
            "severity": e.severity,
            "dedup_count": e.dedup_count,
            "received_at": _aware(e.received_at).isoformat(),
        }
        for e in events
    ]
    edges = [
        {
            "source": str(e.id),
            "target": str(incident_id),
            "kind": "member",
            "weight": 1.0,
        }
        for e in events
    ]
    return envelope({"nodes": nodes, "edges": edges})
