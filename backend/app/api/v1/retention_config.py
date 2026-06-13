"""Retention policy (HQ-admin managed; partition drops are physically
cross-tenant, so tenant-admins get read-only visibility)."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, require_admin, require_hq_admin
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.services.audit import record_audit
from app.services.maintenance import get_retention_config

router = APIRouter(prefix="/retention-config", tags=["retention"])

FIELDS = [
    "alert_events_days",
    "incidents_days",
    "notifications_days",
    "audit_days",
    "archive_enabled",
]


class RetentionUpdate(BaseModel):
    alert_events_days: int | None = Field(default=None, ge=0, le=3650)
    incidents_days: int | None = Field(default=None, ge=0, le=3650)
    notifications_days: int | None = Field(default=None, ge=0, le=3650)
    audit_days: int | None = Field(default=None, ge=0, le=3650)
    archive_enabled: bool | None = None


def _out(row) -> dict:
    return {f: getattr(row, f) for f in FIELDS}


@router.get("")
async def read_retention(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await get_retention_config(db)
    await db.commit()
    return envelope(_out(row))


@router.patch("")
async def update_retention(
    body: RetentionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_hq_admin),
):
    row = await get_retention_config(db)
    before = _out(row)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="retention_config",
        resource_id=row.id,
        before=before,
        after=_out(row),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(row)
    return envelope(_out(row))
