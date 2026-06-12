import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import client_ip, get_current_user, require_editor
from app.core.envelope import envelope
from app.core.pagination import decode_cursor, page_meta
from app.db import get_db
from app.models import Group, Incident, User
from app.models.alerting import IncidentEvent, IncidentStatus
from app.schemas.alerting import IncidentDetailOut, IncidentOut
from app.schemas.delivery import NotifyRequest
from app.services.audit import record_audit

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
async def list_incidents(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    status: IncidentStatus | None = None,
    severity: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Incident).order_by(Incident.created_at.desc(), Incident.id.desc())
    if status is not None:
        stmt = stmt.where(Incident.status == status)
    if severity is not None:
        stmt = stmt.where(Incident.severity == severity)
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            t, i = decoded
            stmt = stmt.where(
                or_(
                    Incident.created_at < t,
                    (Incident.created_at == t) & (Incident.id < i),
                )
            )
    res = await db.execute(stmt.limit(limit + 1))
    items, meta = page_meta(list(res.scalars().unique()), limit)
    return envelope(
        [IncidentOut.model_validate(i).model_dump(mode="json") for i in items],
        meta=meta,
    )


async def load_incident(db: AsyncSession, incident_id: uuid.UUID) -> Incident:
    res = await db.execute(
        select(Incident)
        .options(selectinload(Incident.alerts), selectinload(Incident.timeline))
        .where(Incident.id == incident_id)
    )
    incident = res.scalars().unique().one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.get("/{incident_id}")
async def get_incident(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    incident = await load_incident(db, incident_id)
    return envelope(IncidentDetailOut.model_validate(incident).model_dump(mode="json"))


@router.post("/{incident_id}/notify")
async def notify_incident(
    incident_id: uuid.UUID,
    body: NotifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Manual group send (editor+): creates outbox rows; the notification
    worker delivers them asynchronously."""
    from app.notifications.fanout import fan_out_to_group

    incident = await load_incident(db, incident_id)
    group = await db.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    created = await fan_out_to_group(db, incident, group)
    await record_audit(
        db,
        actor_id=user.id,
        action="notify",
        resource_type="incident",
        resource_id=incident.id,
        after={"group_id": str(group.id), "created": created},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"created": created})


@router.post("/{incident_id}/ack")
async def ack_incident(
    incident_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    return await _transition(db, request, user, incident_id, IncidentStatus.acknowledged, "ack")


@router.post("/{incident_id}/resolve")
async def resolve_incident(
    incident_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    return await _transition(db, request, user, incident_id, IncidentStatus.resolved, "resolve")


async def _transition(
    db: AsyncSession,
    request: Request,
    user: User,
    incident_id: uuid.UUID,
    to_status: IncidentStatus,
    action: str,
):
    incident = await load_incident(db, incident_id)
    if incident.status == IncidentStatus.resolved:
        raise HTTPException(status_code=409, detail="Incident already resolved")
    before = incident.status.value
    incident.status = to_status
    incident.updated_by = user.id
    db.add(
        IncidentEvent(
            incident_id=incident.id,
            kind="status_changed",
            payload={"from": before, "to": to_status.value, "by": user.username},
        )
    )
    await record_audit(
        db,
        actor_id=user.id,
        action=action,
        resource_type="incident",
        resource_id=incident.id,
        before={"status": before},
        after={"status": to_status.value},
        ip=client_ip(request),
    )
    await db.commit()
    incident = await load_incident(db, incident_id)
    return envelope(IncidentDetailOut.model_validate(incident).model_dump(mode="json"))
