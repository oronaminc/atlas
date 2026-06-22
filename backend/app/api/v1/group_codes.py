"""Admin CRUD for user-group -> cmdb_service_l2_code mappings (IMP §6). This is
the one managed list; it governs both visibility and notification routing."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_admin
from app.core.envelope import envelope
from app.db import get_db
from app.models import Group, User
from app.models.group import GroupServiceCode
from app.services.audit import record_audit

router = APIRouter(prefix="/groups", tags=["group-service-codes"])


class ServiceCodes(BaseModel):
    codes: list[str]


async def _group_or_404(db: AsyncSession, group_id: uuid.UUID) -> Group:
    g = await db.get(Group, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return g


@router.get("/{group_id}/service-codes")
async def list_codes(
    group_id: uuid.UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    await _group_or_404(db, group_id)
    codes = (
        await db.execute(
            select(GroupServiceCode.cmdb_service_l2_code)
            .where(GroupServiceCode.group_id == group_id)
            .order_by(GroupServiceCode.cmdb_service_l2_code)
        )
    ).scalars()
    return envelope({"codes": list(codes)})


@router.put("/{group_id}/service-codes")
async def set_codes(
    group_id: uuid.UUID,
    body: ServiceCodes,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Replace the group's full l2-code set (idempotent)."""
    group = await _group_or_404(db, group_id)
    existing = {
        c: row
        for c, row in (
            await db.execute(
                select(GroupServiceCode.cmdb_service_l2_code, GroupServiceCode).where(
                    GroupServiceCode.group_id == group_id
                )
            )
        ).all()
    }
    wanted = {c.strip() for c in body.codes if c.strip()}
    for code in wanted - existing.keys():
        db.add(GroupServiceCode(group_id=group.id, cmdb_service_l2_code=code))
    for code in existing.keys() - wanted:
        await db.delete(existing[code])
    await record_audit(
        db,
        actor_id=user.id,
        action="set_service_codes",
        resource_type="group",
        resource_id=group.id,
        after={"codes": sorted(wanted)},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"codes": sorted(wanted)})
