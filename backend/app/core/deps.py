import uuid

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.core.tenancy import resolve_tenant_slug, set_tenant_scope
from app.db import get_db
from app.models import User
from app.models.group import GroupRole
from app.models.user import GlobalRole

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized()
    try:
        payload = decode_token(credentials.credentials, "access")
        user_id = uuid.UUID(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, ValueError) as e:
        raise _unauthorized("Invalid token") from e

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("User not found or inactive")
    # Tenancy choke point: every authenticated request scopes its DB session
    # here. HQ users (tenant_id NULL) get an unscoped (= all tenants) session.
    set_tenant_scope(db, user.tenant_id)
    return user


def require_roles(*roles: GlobalRole):
    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return checker


require_admin = require_roles(GlobalRole.admin)
require_editor = require_roles(GlobalRole.admin, GlobalRole.editor)


async def require_hq_admin(user: User = Depends(require_admin)) -> User:
    """Super-admin: admin role AND HQ scope (tenant_id NULL).
    Tenant-admins (admin with a tenant) are rejected."""
    if user.tenant_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="HQ admin only")
    return user


async def apply_tenant_param(
    tenant: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    """Optional `?tenant=<slug>` drill-down for HQ users on aggregate views
    (stats/graph/incidents/alerts). Ignored for tenant users — their session
    scope is already locked by get_current_user."""
    if tenant and user.tenant_id is None:
        target = await resolve_tenant_slug(db, tenant)
        if target is None:
            raise HTTPException(status_code=404, detail="Unknown tenant")
        set_tenant_scope(db, target.id)
    return user


def user_group_ids(user: User) -> set[uuid.UUID]:
    return {m.group_id for m in user.memberships}


def user_managed_group_ids(user: User) -> set[uuid.UUID]:
    return {m.group_id for m in user.memberships if m.role_in_group == GroupRole.manager}


async def is_group_manager(user: User, group_id: uuid.UUID) -> bool:
    if user.role == GlobalRole.admin:
        return True
    return group_id in user_managed_group_ids(user)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    res = await db.execute(select(User).where(User.email == email))
    return res.scalar_one_or_none()


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
