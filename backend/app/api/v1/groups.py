import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_admin
from app.core.envelope import envelope
from app.core.pagination import decode_cursor, page_meta
from app.db import get_db
from app.models import Group, User, UserGroup
from app.schemas.group import (
    GroupCreate,
    GroupMemberAdd,
    GroupMemberOut,
    GroupOut,
    GroupUpdate,
)
from app.services.audit import record_audit, snapshot
from app.services.permissions import can_manage_group

router = APIRouter(prefix="/groups", tags=["groups"])

GROUP_AUDIT_FIELDS = ["name", "description"]


def group_to_out(group: Group) -> dict:
    out = GroupOut.model_validate(group)
    out.member_count = len(group.memberships)
    return out.model_dump(mode="json")


@router.get("")
async def list_groups(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Group).order_by(Group.created_at.desc(), Group.id.desc())
    if q:
        stmt = stmt.where(Group.name.ilike(f"%{q}%"))
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            t, i = decoded
            stmt = stmt.where(
                or_(Group.created_at < t, (Group.created_at == t) & (Group.id < i))
            )
    res = await db.execute(stmt.limit(limit + 1))
    items, meta = page_meta(list(res.scalars().unique()), limit)
    return envelope([group_to_out(g) for g in items], meta=meta)


@router.post("", status_code=201)
async def create_group(
    body: GroupCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    dup = await db.execute(select(Group).where(Group.name == body.name))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Group name already exists")
    group = Group(name=body.name, description=body.description, created_by=admin.id)
    db.add(group)
    await db.flush()
    await record_audit(
        db,
        actor_id=admin.id,
        action="create",
        resource_type="group",
        resource_id=group.id,
        after=snapshot(group, GROUP_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(group)
    return envelope(group_to_out(group))


@router.get("/{group_id}")
async def get_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return envelope(group_to_out(group))


@router.patch("/{group_id}")
async def update_group(
    group_id: uuid.UUID,
    body: GroupUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if not can_manage_group(user, group_id):
        raise HTTPException(status_code=403, detail="Not a manager of this group")
    before = snapshot(group, GROUP_AUDIT_FIELDS)
    if body.name is not None:
        group.name = body.name
    if body.description is not None:
        group.description = body.description
    group.updated_by = user.id
    await record_audit(
        db,
        actor_id=user.id,
        action="update",
        resource_type="group",
        resource_id=group.id,
        before=before,
        after=snapshot(group, GROUP_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(group)
    return envelope(group_to_out(group))


@router.delete("/{group_id}")
async def delete_group(
    group_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    before = snapshot(group, GROUP_AUDIT_FIELDS)
    await db.delete(group)
    await record_audit(
        db,
        actor_id=admin.id,
        action="delete",
        resource_type="group",
        resource_id=group_id,
        before=before,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})


@router.get("/{group_id}/members")
async def list_members(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    members = [
        GroupMemberOut(
            user_id=m.user_id,
            username=m.user.username,
            email=m.user.email,
            role_in_group=m.role_in_group,
        ).model_dump(mode="json")
        for m in group.memberships
    ]
    return envelope(members)


@router.post("/{group_id}/members", status_code=201)
async def add_member(
    group_id: uuid.UUID,
    body: GroupMemberAdd,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if not can_manage_group(user, group_id):
        raise HTTPException(status_code=403, detail="Not a manager of this group")
    target = await db.get(User, body.user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    dup = await db.execute(
        select(UserGroup).where(
            UserGroup.group_id == group_id, UserGroup.user_id == body.user_id
        )
    )
    existing = dup.scalar_one_or_none()
    if existing:
        existing.role_in_group = body.role_in_group
    else:
        db.add(
            UserGroup(
                user_id=body.user_id,
                group_id=group_id,
                role_in_group=body.role_in_group,
                created_by=user.id,
            )
        )
    await record_audit(
        db,
        actor_id=user.id,
        action="add_member",
        resource_type="group",
        resource_id=group_id,
        after={"user_id": str(body.user_id), "role_in_group": body.role_in_group.value},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})


@router.delete("/{group_id}/members/{user_id}")
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_group(user, group_id):
        raise HTTPException(status_code=403, detail="Not a manager of this group")
    res = await db.execute(
        select(UserGroup).where(
            UserGroup.group_id == group_id, UserGroup.user_id == user_id
        )
    )
    membership = res.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    await db.delete(membership)
    await record_audit(
        db,
        actor_id=user.id,
        action="remove_member",
        resource_type="group",
        resource_id=group_id,
        before={"user_id": str(user_id)},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})
