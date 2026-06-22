"""Resource-level permission checks (RBAC, spec §5).

- admin: everything
- editor: incident/threshold actions
- viewer: read-only
- group manager: manage members of managed groups
"""

import uuid

from app.core.deps import user_managed_group_ids
from app.models import User
from app.models.user import GlobalRole


def can_manage_group(user: User, group_id: uuid.UUID) -> bool:
    if user.role == GlobalRole.admin:
        return True
    return group_id in user_managed_group_ids(user)
