import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_editor
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.alerting import AlertEvent
from app.models.threshold import RuleCatalog, ThresholdOverride
from app.schemas.threshold import (
    RuleCatalogOut,
    RuleCatalogUpdate,
    ThresholdOverrideCreate,
    ThresholdOverrideOut,
    ThresholdOverrideUpdate,
)
from app.services.audit import record_audit

router = APIRouter(tags=["thresholds"])


# ---- rule catalog (per-alertname threshold metadata) ----


@router.get("/rule-catalog")
async def list_catalog(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """Union of cataloged rows (with metadata) and alertnames merely seen in
    events (metadata NULL until configured). Feeds the threshold + mute UIs."""
    rows = {
        r.alertname: RuleCatalogOut.model_validate(r).model_dump()
        for r in (await db.execute(select(RuleCatalog))).scalars()
    }
    seen = (await db.execute(select(AlertEvent.name).distinct())).scalars()
    for name in seen:
        rows.setdefault(
            name, {"alertname": name, "comparator": None, "unit": None, "value_query": None}
        )
    return envelope(sorted(rows.values(), key=lambda r: r["alertname"]))


@router.patch("/rule-catalog/{alertname}")
async def upsert_catalog(
    alertname: str,
    body: RuleCatalogUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    row = (
        await db.execute(select(RuleCatalog).where(RuleCatalog.alertname == alertname))
    ).scalar_one_or_none()
    if row is None:
        row = RuleCatalog(alertname=alertname)
        db.add(row)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    await db.flush()
    await record_audit(
        db,
        actor_id=user.id,
        action="upsert",
        resource_type="rule_catalog",
        resource_id=row.id,
        after=data,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope(RuleCatalogOut.model_validate(row).model_dump())


# ---- threshold overrides (server > group > default) ----


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
