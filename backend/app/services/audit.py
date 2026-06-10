import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record_audit(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    emergency: bool = False,
) -> AuditLog:
    """Appends an audit entry to the current transaction (committed with it)."""
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before=before,
        after=after,
        ip=ip,
        emergency=emergency,
    )
    db.add(log)
    return log


def snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    """JSON-safe snapshot of selected model fields for before/after diffs."""
    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(obj, field, None)
        if hasattr(value, "value"):  # enums
            value = value.value
        elif isinstance(value, uuid.UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        result[field] = value
    return result
