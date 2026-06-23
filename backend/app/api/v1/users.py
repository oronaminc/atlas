import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import user_to_out
from app.core.deps import client_ip, get_current_user, require_admin
from app.core.envelope import envelope
from app.core.pagination import decode_cursor, offset_page, page_meta
from app.core.security import hash_password
from app.db import get_db
from app.models import User
from app.schemas.user import MeUpdate, PasswordReset, UserCreate, UserUpdate
from app.services.audit import record_audit, snapshot

router = APIRouter(prefix="/users", tags=["users"])

USER_AUDIT_FIELDS = ["email", "username", "role", "is_active"]


@router.get("")
async def list_users(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    stmt = select(User).order_by(User.created_at.desc(), User.id.desc())
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(User.email.ilike(pattern), User.username.ilike(pattern)))
    if page is not None:  # numbered (1..N) pagination
        items, meta = await offset_page(db, stmt, page=page, page_size=page_size)
        return envelope([user_to_out(u).model_dump(mode="json") for u in items], meta=meta)
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            t, i = decoded
            stmt = stmt.where(or_(User.created_at < t, (User.created_at == t) & (User.id < i)))
    res = await db.execute(stmt.limit(limit + 1))
    items, meta = page_meta(list(res.scalars().unique()), limit)
    return envelope([user_to_out(u).model_dump(mode="json") for u in items], meta=meta)


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: uuid.UUID,
    body: PasswordReset,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-direct password reset: set a new password immediately (NO email)."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = hash_password(body.new_password)
    user.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="reset_password",
        resource_type="user",
        resource_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})


@router.post("", status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    existing = await db.execute(
        select(User).where(or_(User.email == body.email, User.username == body.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email or username already exists")
    if body.auth_provider.value == "local" and not body.password:
        raise HTTPException(status_code=400, detail="Local accounts require a password")

    user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password) if body.password else None,
        role=body.role,
        auth_provider=body.auth_provider,
        created_by=admin.id,
    )
    db.add(user)
    await db.flush()
    await record_audit(
        db,
        actor_id=admin.id,
        action="create",
        resource_type="user",
        resource_id=user.id,
        after=snapshot(user, USER_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(user)
    return envelope(user_to_out(user).model_dump(mode="json"))


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return envelope(user_to_out(user).model_dump(mode="json"))


@router.patch("/me")
async def update_me(
    body: MeUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    before = snapshot(user, USER_AUDIT_FIELDS)
    if body.username:
        dup = await db.execute(
            select(User).where(User.username == body.username, User.id != user.id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username already exists")
        user.username = body.username
    await record_audit(
        db,
        actor_id=user.id,
        action="update",
        resource_type="user",
        resource_id=user.id,
        before=before,
        after=snapshot(user, USER_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(user)
    return envelope(user_to_out(user).model_dump(mode="json"))


@router.get("/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return envelope(user_to_out(user).model_dump(mode="json"))


@router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    before = snapshot(user, USER_AUDIT_FIELDS)
    if body.username is not None:
        user.username = body.username
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.telegram_chat_id is not None:
        user.telegram_chat_id = body.telegram_chat_id
    user.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="user",
        resource_id=user.id,
        before=before,
        after=snapshot(user, USER_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(user)
    return envelope(user_to_out(user).model_dump(mode="json"))


@router.delete("/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    before = snapshot(user, USER_AUDIT_FIELDS)
    await db.delete(user)
    await record_audit(
        db,
        actor_id=admin.id,
        action="delete",
        resource_type="user",
        resource_id=user_id,
        before=before,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})
