import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_editor
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.alerting import AlertEvent
from app.models.delivery import NotificationMute
from app.schemas.mute import MuteCreate, MuteOut
from app.services.audit import record_audit

router = APIRouter(prefix="/mutes", tags=["mutes"])


@router.get("")
async def list_mutes(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    mutes = list(
        (
            await db.execute(select(NotificationMute).order_by(NotificationMute.created_at.desc()))
        ).scalars()
    )
    return envelope([MuteOut.model_validate(m).model_dump(mode="json") for m in mutes])


@router.post("", status_code=201)
async def create_mute(
    body: MuteCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    # App-level dedupe: the DB unique constraint can't catch duplicates whose
    # tuple contains NULLs (tenant_id/target_group_id) — SQL treats NULL as
    # distinct. This SELECT is auto-scoped to the caller's tenant by the choke
    # point. (== None compiles to IS NULL.)
    dup = (
        (
            await db.execute(
                select(NotificationMute).where(
                    NotificationMute.target_type == body.target_type,
                    NotificationMute.target_cmdb_ci == body.target_cmdb_ci,
                    NotificationMute.target_group_id == body.target_group_id,
                    NotificationMute.alertname == body.alertname,
                )
            )
        )
        .scalars()
        .first()
    )
    if dup is not None:
        raise HTTPException(status_code=409, detail="Mute already exists")

    m = NotificationMute(
        target_type=body.target_type,
        target_cmdb_ci=body.target_cmdb_ci,
        target_group_id=body.target_group_id,
        alertname=body.alertname,
        reason=body.reason,
        enabled=True,
    )
    db.add(m)
    await db.flush()
    await record_audit(
        db,
        actor_id=user.id,
        action="create",
        resource_type="notification_mute",
        resource_id=m.id,
        after={"target_type": m.target_type, "alertname": m.alertname},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope(MuteOut.model_validate(m).model_dump(mode="json"))


@router.delete("/{mute_id}")
async def delete_mute(
    mute_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    m = await db.get(NotificationMute, mute_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Mute not found")
    await record_audit(
        db,
        actor_id=user.id,
        action="delete",
        resource_type="notification_mute",
        resource_id=m.id,
        before={"target_type": m.target_type, "alertname": m.alertname},
        ip=client_ip(request),
    )
    await db.delete(m)
    await db.commit()
    return envelope({"ok": True})


@router.get("/rule-catalog")
async def rule_catalog(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """Alertnames seen in ingested events (auto-scoped by the tenancy choke
    point) — feeds the mute rule picker. No Ruler import in Model 2."""
    names = list(
        (await db.execute(select(AlertEvent.name).distinct().order_by(AlertEvent.name))).scalars()
    )
    return envelope({"alertnames": names})
