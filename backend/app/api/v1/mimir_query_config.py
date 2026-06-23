"""Admin config for the Mimir label-discovery proxy lookback window (single row).
Tuning the window (DB-authoritative, default 1h) bounds label queries so a stale
Mimir bucket index / full-retention range can't 422 the whole query — no code
change or image rebuild needed."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, require_admin
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.services.audit import record_audit
from app.services.mimir_sync import get_mimir_query_config

router = APIRouter(prefix="/mimir-query-config", tags=["mimir-query-config"])


class MimirQueryUpdate(BaseModel):
    label_query_lookback_hours: int | None = Field(default=None, ge=1, le=720)  # 1h–30d


def _out(row) -> dict:
    return {"label_query_lookback_hours": row.label_query_lookback_hours}


@router.get("")
async def read_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await get_mimir_query_config(db)
    await db.commit()
    return envelope(_out(row))


@router.patch("")
async def update_config(
    body: MimirQueryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = await get_mimir_query_config(db)
    before = _out(row)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="mimir_query_config",
        resource_id=row.id,
        before=before,
        after=_out(row),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(row)
    return envelope(_out(row))
