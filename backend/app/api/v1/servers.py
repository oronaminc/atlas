import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_editor
from app.core.envelope import envelope
from app.core.pagination import decode_cursor, page_meta
from app.db import get_db
from app.models import AlertRule, Server, User
from app.models.rule import ScopeType
from app.schemas.rule import AlertRuleOut
from app.schemas.server import ServerCreate, ServerOut, ServerUpdate
from app.services.audit import record_audit, snapshot

router = APIRouter(prefix="/servers", tags=["servers"])

SERVER_AUDIT_FIELDS = ["name", "labels", "description", "owner_group_id"]


@router.get("")
async def list_servers(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Server).order_by(Server.created_at.desc(), Server.id.desc())
    if q:
        stmt = stmt.where(Server.name.ilike(f"%{q}%"))
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            t, i = decoded
            stmt = stmt.where(
                or_(Server.created_at < t, (Server.created_at == t) & (Server.id < i))
            )
    res = await db.execute(stmt.limit(limit + 1))
    items, meta = page_meta(list(res.scalars().unique()), limit)
    return envelope([ServerOut.model_validate(s).model_dump(mode="json") for s in items], meta=meta)


@router.post("", status_code=201)
async def create_server(
    body: ServerCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    dup = await db.execute(select(Server).where(Server.name == body.name))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Server name already exists")
    server = Server(
        name=body.name,
        labels=body.labels,
        description=body.description,
        owner_group_id=body.owner_group_id,
        created_by=user.id,
    )
    db.add(server)
    await db.flush()
    await record_audit(
        db,
        actor_id=user.id,
        action="create",
        resource_type="server",
        resource_id=server.id,
        after=snapshot(server, SERVER_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(server)
    return envelope(ServerOut.model_validate(server).model_dump(mode="json"))


@router.get("/{server_id}")
async def get_server(
    server_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    server = await db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return envelope(ServerOut.model_validate(server).model_dump(mode="json"))


@router.patch("/{server_id}")
async def update_server(
    server_id: uuid.UUID,
    body: ServerUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    server = await db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    before = snapshot(server, SERVER_AUDIT_FIELDS)
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(server, field, value)
    server.updated_by = user.id
    await record_audit(
        db,
        actor_id=user.id,
        action="update",
        resource_type="server",
        resource_id=server.id,
        before=before,
        after=snapshot(server, SERVER_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(server)
    return envelope(ServerOut.model_validate(server).model_dump(mode="json"))


@router.delete("/{server_id}")
async def delete_server(
    server_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    server = await db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    before = snapshot(server, SERVER_AUDIT_FIELDS)
    await db.delete(server)
    await record_audit(
        db,
        actor_id=user.id,
        action="delete",
        resource_type="server",
        resource_id=server_id,
        before=before,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})


@router.get("/{server_id}/rules")
async def server_rules(
    server_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Rules scoped to this server plus the global rules that also apply."""
    server = await db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    res = await db.execute(
        select(AlertRule)
        .where(
            or_(
                (AlertRule.scope_type == ScopeType.server) & (AlertRule.scope_ref_id == server_id),
                AlertRule.scope_type == ScopeType.global_,
            )
        )
        .order_by(AlertRule.created_at.desc())
    )
    rules = [AlertRuleOut.model_validate(r).model_dump(mode="json") for r in res.scalars().unique()]
    return envelope(rules)
