"""Resource-level permission checks (RBAC, spec §5).

- admin: everything
- editor: rule CRUD within own group/server scope, emergency apply
- viewer: read-only
- group manager: manage members + group-scoped rules of managed groups
- scope_type=user rules: only the owner or an admin
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import user_group_ids, user_managed_group_ids
from app.models import AlertRule, Server, User
from app.models.rule import ScopeType
from app.models.user import GlobalRole


async def can_write_rule(db: AsyncSession, user: User, rule: AlertRule) -> bool:
    return await can_write_rule_scope(db, user, rule.scope_type, rule.scope_ref_id)


async def can_write_rule_scope(
    db: AsyncSession,
    user: User,
    scope_type: ScopeType,
    scope_ref_id: uuid.UUID | None,
) -> bool:
    if user.role == GlobalRole.admin:
        return True
    if user.role == GlobalRole.viewer:
        # group managers may manage group-scoped rules even with a viewer global role
        if scope_type == ScopeType.group and scope_ref_id in user_managed_group_ids(
            user
        ):
            return True
        return False

    # editor
    if scope_type == ScopeType.user:
        return scope_ref_id == user.id
    if scope_type == ScopeType.group:
        return scope_ref_id in user_group_ids(user)
    if scope_type == ScopeType.server:
        if scope_ref_id is None:
            return False
        server = await db.get(Server, scope_ref_id)
        if server is None:
            return False
        if server.owner_group_id is None:
            # unowned servers are editable by any editor
            return True
        return server.owner_group_id in user_group_ids(user)
    if scope_type == ScopeType.global_:
        # global rules are admin-only to write
        return False
    return False


def can_manage_group(user: User, group_id: uuid.UUID) -> bool:
    if user.role == GlobalRole.admin:
        return True
    return group_id in user_managed_group_ids(user)
