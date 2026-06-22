import uuid

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.core.visibility import allowed_l2_codes, set_l2_scope
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
    # Visibility choke point (IMP §6): admins see everything (None = bypass);
    # non-admins see only alerts/incidents whose l2_code their groups map to.
    if user.role == GlobalRole.admin:
        set_l2_scope(db, None)
    else:
        set_l2_scope(db, await allowed_l2_codes(db, user.id))
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


# Tenancy was removed (IMP cleanup); HQ-admin == admin now. Kept as an alias so
# admin-only config endpoints (e.g. retention) read intent at the call site.
require_hq_admin = require_admin


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
