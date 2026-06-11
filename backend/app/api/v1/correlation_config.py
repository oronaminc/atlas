from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_admin
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.schemas.alerting import CorrelationConfigOut, CorrelationConfigUpdate
from app.services.audit import record_audit
from app.services.correlation.config import get_config

router = APIRouter(prefix="/correlation-config", tags=["correlation"])

AUDIT_FIELDS = ["dedup_window_seconds", "correlation_window_seconds", "group_attrs"]


def _snapshot(config) -> dict:
    return {f: getattr(config, f) for f in AUDIT_FIELDS}


@router.get("")
async def read_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    config = await get_config(db)
    await db.commit()  # persist seeded defaults on first read
    return envelope(CorrelationConfigOut.model_validate(config).model_dump(mode="json"))


@router.patch("")
async def update_config(
    body: CorrelationConfigUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    config = await get_config(db)
    before = _snapshot(config)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(config, field, value)
    config.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="correlation_config",
        resource_id=config.id,
        before=before,
        after=_snapshot(config),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(config)
    return envelope(CorrelationConfigOut.model_validate(config).model_dump(mode="json"))
