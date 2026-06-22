import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import client_ip, get_current_user, require_editor
from app.core.envelope import envelope
from app.core.pagination import decode_cursor, page_meta
from app.db import get_db
from app.models import Group, Incident, User
from app.models.alerting import AlertEvent, IncidentEvent, IncidentStatus
from app.models.base import utcnow
from app.models.llm import IncidentAnalysis
from app.schemas.alerting import IncidentDetailOut, IncidentOut
from app.schemas.delivery import NotifyRequest
from app.schemas.llm import IncidentAnalysisOut
from app.services import incident_service
from app.services.audit import record_audit

router = APIRouter(prefix="/incidents", tags=["incidents"])


class PromoteRequest(BaseModel):
    alert_id: uuid.UUID
    title: str | None = None


class AttachRequest(BaseModel):
    alert_id: uuid.UUID


class ChannelToggles(BaseModel):
    notify_email: bool | None = None
    notify_telegram: bool | None = None
    notify_oncall: bool | None = None


async def _get_alert(db: AsyncSession, alert_id: uuid.UUID) -> AlertEvent:
    alert = (
        await db.execute(select(AlertEvent).where(AlertEvent.id == alert_id))
    ).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.get("")
async def list_incidents(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    status: str | None = Query(default=None, description="comma-separated IncidentStatus values"),
    severity: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Incident).order_by(Incident.created_at.desc(), Incident.id.desc())
    if status is not None:
        try:
            statuses = [IncidentStatus(s.strip()) for s in status.split(",") if s.strip()]
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid status: {e}") from e
        if statuses:
            stmt = stmt.where(Incident.status.in_(statuses))
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


@router.post("", status_code=201)
async def promote_alert_to_incident(
    body: PromoteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Manual promote: a single alert -> a NEW incident (any severity, size 1)."""
    alert = await _get_alert(db, body.alert_id)
    try:
        incident = await incident_service.promote_alert(db, alert, utcnow(), title=body.title)
    except incident_service.AlreadyAttachedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await record_audit(
        db,
        actor_id=user.id,
        action="promote",
        resource_type="incident",
        resource_id=incident.id,
        after={"alert_id": str(alert.id)},
        ip=client_ip(request),
    )
    await db.commit()
    incident = await load_incident(db, incident.id)
    return envelope(IncidentDetailOut.model_validate(incident).model_dump(mode="json"))


@router.post("/{incident_id}/alerts")
async def attach_alert(
    incident_id: uuid.UUID,
    body: AttachRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Manual attach: add an existing alert into this incident."""
    incident = await load_incident(db, incident_id)
    alert = await _get_alert(db, body.alert_id)
    try:
        await incident_service.attach_to_incident(db, incident, alert, utcnow())
    except incident_service.AlreadyAttachedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await record_audit(
        db,
        actor_id=user.id,
        action="attach_alert",
        resource_type="incident",
        resource_id=incident.id,
        after={"alert_id": str(alert.id)},
        ip=client_ip(request),
    )
    await db.commit()
    incident = await load_incident(db, incident_id)
    return envelope(IncidentDetailOut.model_validate(incident).model_dump(mode="json"))


@router.delete("/{incident_id}/alerts/{alert_id}")
async def detach_alert(
    incident_id: uuid.UUID,
    alert_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Manual detach. Emptying the incident auto-resolves it (decision D)."""
    incident = await load_incident(db, incident_id)
    alert = await _get_alert(db, alert_id)
    await incident_service.detach_alert(db, incident, alert, utcnow())
    await record_audit(
        db,
        actor_id=user.id,
        action="detach_alert",
        resource_type="incident",
        resource_id=incident.id,
        before={"alert_id": str(alert.id)},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})


@router.patch("/{incident_id}")
async def update_incident_channels(
    incident_id: uuid.UUID,
    body: ChannelToggles,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Per-incident notification channel toggles (IMP §7)."""
    incident = await load_incident(db, incident_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(incident, k, v)
    db.add(IncidentEvent(incident_id=incident.id, kind="channels_changed", payload=data))
    await record_audit(
        db,
        actor_id=user.id,
        action="update_channels",
        resource_type="incident",
        resource_id=incident.id,
        after=data,
        ip=client_ip(request),
    )
    await db.commit()
    incident = await load_incident(db, incident_id)
    return envelope(IncidentDetailOut.model_validate(incident).model_dump(mode="json"))


@router.post("/{incident_id}/analyze")
async def analyze_incident(
    incident_id: uuid.UUID,
    request: Request,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Enqueue an LLM analysis (editor+). Idempotent: an existing job is
    reused unless ?force=true. The llm_worker runs it async; poll
    GET /incidents/{id}/analysis. tenant_id is stamped from the incident so
    the worker sends only to this service's configured endpoint."""
    incident = await load_incident(db, incident_id)  # 404 if cross-tenant
    existing = (
        await db.execute(
            select(IncidentAnalysis).where(IncidentAnalysis.incident_id == incident.id)
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = IncidentAnalysis(incident_id=incident.id, status="pending")
        db.add(existing)
    elif force or existing.status in ("done", "failed"):
        existing.status = "pending"
        existing.claimed_at = None
        existing.claimed_by = None
        existing.attempts = 0
        if force:
            existing.prompt_hash = None  # bust the cache
    await record_audit(
        db,
        actor_id=user.id,
        action="analyze",
        resource_type="incident",
        resource_id=incident.id,
        after={"force": force},
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(existing)
    return envelope(IncidentAnalysisOut.model_validate(existing).model_dump(mode="json"))


@router.get("/{incident_id}/analysis")
async def get_incident_analysis(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    incident = await load_incident(db, incident_id)  # tenancy-scoped 404
    row = (
        await db.execute(
            select(IncidentAnalysis).where(IncidentAnalysis.incident_id == incident.id)
        )
    ).scalar_one_or_none()
    if row is None:
        return envelope(None)
    return envelope(IncidentAnalysisOut.model_validate(row).model_dump(mode="json"))


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


@router.post("/{incident_id}/suppress")
async def suppress_incident(
    incident_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Explicit mute (editor+): drops the incident out of active views.
    It keeps absorbing matching alerts without re-notifying. Reversible."""
    return await _transition(db, request, user, incident_id, IncidentStatus.suppressed, "suppress")


@router.post("/{incident_id}/unsuppress")
async def unsuppress_incident(
    incident_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    return await _transition(db, request, user, incident_id, IncidentStatus.open, "unsuppress")


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
    if action == "unsuppress" and incident.status != IncidentStatus.suppressed:
        raise HTTPException(status_code=409, detail="Incident is not suppressed")
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
