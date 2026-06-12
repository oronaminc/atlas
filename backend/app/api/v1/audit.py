import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.core.pagination import decode_cursor, page_meta
from app.db import get_db
from app.models import AuditLog, User
from app.schemas.audit import AuditLogOut

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
async def list_audit_logs(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    emergency: bool | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if emergency is not None:
        stmt = stmt.where(AuditLog.emergency == emergency)
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            t, i = decoded
            stmt = stmt.where(
                or_(
                    AuditLog.created_at < t,
                    (AuditLog.created_at == t) & (AuditLog.id < i),
                )
            )
    res = await db.execute(stmt.limit(limit + 1))
    items, meta = page_meta(list(res.scalars()), limit)
    return envelope(
        [AuditLogOut.model_validate(a).model_dump(mode="json") for a in items],
        meta=meta,
    )
