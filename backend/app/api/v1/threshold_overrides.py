import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_editor
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.threshold import ThresholdOverride
from app.schemas.threshold import (
    ThresholdOverrideCreate,
    ThresholdOverrideOut,
    ThresholdOverrideUpdate,
)
from app.services.audit import record_audit

router = APIRouter(tags=["thresholds"])


# ---- threshold overrides (per-server cmdb_ci > per-service label > rule base) ----


@router.get("/threshold-overrides")
async def list_overrides(
    alertname: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(ThresholdOverride).order_by(ThresholdOverride.alertname)
    if alertname:
        stmt = stmt.where(ThresholdOverride.alertname == alertname)
    rows = (await db.execute(stmt)).scalars()
    return envelope([ThresholdOverrideOut.model_validate(o).model_dump(mode="json") for o in rows])


@router.post("/threshold-overrides", status_code=201)
async def create_override(
    body: ThresholdOverrideCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    dup = (
        await db.execute(
            select(ThresholdOverride).where(
                ThresholdOverride.alertname == body.alertname,
                ThresholdOverride.target_cmdb_ci == body.target_cmdb_ci,
                ThresholdOverride.target_label_key == body.target_label_key,
                ThresholdOverride.target_label_value == body.target_label_value,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail="Override already exists")
    o = ThresholdOverride(
        alertname=body.alertname,
        target_cmdb_ci=body.target_cmdb_ci,
        target_label_key=body.target_label_key,
        target_label_value=body.target_label_value,
        value=body.value,
    )
    db.add(o)
    await db.flush()
    await record_audit(
        db,
        actor_id=user.id,
        action="create",
        resource_type="threshold_override",
        resource_id=o.id,
        after={"alertname": o.alertname, "value": o.value},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope(ThresholdOverrideOut.model_validate(o).model_dump(mode="json"))


@router.patch("/threshold-overrides/{override_id}")
async def update_override(
    override_id: uuid.UUID,
    body: ThresholdOverrideUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    o = await db.get(ThresholdOverride, override_id)
    if o is None:
        raise HTTPException(status_code=404, detail="Override not found")
    o.value = body.value
    await record_audit(
        db,
        actor_id=user.id,
        action="update",
        resource_type="threshold_override",
        resource_id=o.id,
        after={"value": o.value},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope(ThresholdOverrideOut.model_validate(o).model_dump(mode="json"))


@router.delete("/threshold-overrides/{override_id}")
async def delete_override(
    override_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    o = await db.get(ThresholdOverride, override_id)
    if o is None:
        raise HTTPException(status_code=404, detail="Override not found")
    await record_audit(
        db,
        actor_id=user.id,
        action="delete",
        resource_type="threshold_override",
        resource_id=o.id,
        before={"alertname": o.alertname},
        ip=client_ip(request),
    )
    await db.delete(o)
    await db.commit()
    return envelope({"ok": True})
