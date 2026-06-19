import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_editor
from app.core.envelope import envelope
from app.db import get_db
from app.models import Server, ServerGroup, User
from app.schemas.server_group import (
    CMDB_CI_RE,
    BulkMembersRequest,
    BulkMembersResult,
    ServerGroupCreate,
    ServerGroupOut,
    ServerGroupUpdate,
    ServerOut,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/server-groups", tags=["server-groups"])


async def _get_or_404(db: AsyncSession, group_id: uuid.UUID) -> ServerGroup:
    g = await db.get(ServerGroup, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Server group not found")
    return g


async def _member_count(db: AsyncSession, group_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Server).where(Server.server_group_id == group_id)
        )
    ).scalar_one()


def _out(g: ServerGroup, count: int) -> dict:
    o = ServerGroupOut.model_validate(g)
    o.member_count = count
    return o.model_dump(mode="json")


@router.get("")
async def list_groups(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    groups = list((await db.execute(select(ServerGroup).order_by(ServerGroup.name))).scalars())
    return envelope([_out(g, await _member_count(db, g.id)) for g in groups])


@router.post("", status_code=201)
async def create_group(
    body: ServerGroupCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    g = ServerGroup(name=body.name, description=body.description)
    db.add(g)
    await db.flush()
    await record_audit(
        db,
        actor_id=user.id,
        action="create",
        resource_type="server_group",
        resource_id=g.id,
        after={"name": g.name},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope(_out(g, 0))


@router.patch("/{group_id}")
async def update_group(
    group_id: uuid.UUID,
    body: ServerGroupUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    g = await _get_or_404(db, group_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(g, k, v)
    await record_audit(
        db,
        actor_id=user.id,
        action="update",
        resource_type="server_group",
        resource_id=g.id,
        after=data,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope(_out(g, await _member_count(db, g.id)))


@router.delete("/{group_id}")
async def delete_group(
    group_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    g = await _get_or_404(db, group_id)
    await record_audit(
        db,
        actor_id=user.id,
        action="delete",
        resource_type="server_group",
        resource_id=g.id,
        before={"name": g.name},
        ip=client_ip(request),
    )
    await db.delete(g)  # Server.server_group_id -> SET NULL
    await db.commit()
    return envelope({"ok": True})


@router.get("/{group_id}/members")
async def list_members(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    await _get_or_404(db, group_id)
    servers = list(
        (
            await db.execute(
                select(Server).where(Server.server_group_id == group_id).order_by(Server.cmdb_ci)
            )
        ).scalars()
    )
    return envelope([ServerOut.model_validate(s).model_dump(mode="json") for s in servers])


@router.post("/{group_id}/members/bulk")
async def bulk_add_members(
    group_id: uuid.UUID,
    body: BulkMembersRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Upsert Server rows by cmdb_ci and (re)assign them into this group (1:1).
    Dedupes the input, validates cmdb_ci, reports rejected entries."""
    g = await _get_or_404(db, group_id)

    seen: set[str] = set()
    valid: list[str] = []
    rejected: list[str] = []
    for raw in body.cmdb_cis:
        if not raw or raw in seen:
            if raw and raw in seen:
                continue
            rejected.append(raw)
            continue
        if not CMDB_CI_RE.match(raw):
            rejected.append(raw)
            continue
        seen.add(raw)
        valid.append(raw)

    existing = (
        {
            s.cmdb_ci: s
            for s in (await db.execute(select(Server).where(Server.cmdb_ci.in_(valid)))).scalars()
            if s.cmdb_ci
        }
        if valid
        else {}
    )

    added = reassigned = already = 0
    for cmdb in valid:
        s = existing.get(cmdb)
        if s is None:
            db.add(Server(name=cmdb, cmdb_ci=cmdb, server_group_id=g.id))
            added += 1
        elif s.server_group_id == g.id:
            already += 1
        else:
            s.server_group_id = g.id  # 1:1 — move out of any prior group
            reassigned += 1

    await record_audit(
        db,
        actor_id=user.id,
        action="bulk_members",
        resource_type="server_group",
        resource_id=g.id,
        after={"added": added, "reassigned": reassigned, "rejected": len(rejected)},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope(
        BulkMembersResult(
            added=added, reassigned=reassigned, already_in_group=already, rejected=rejected
        ).model_dump()
    )
