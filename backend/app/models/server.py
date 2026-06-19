import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JsonType, TenantScoped, TimestampedBase


class ServerGroup(TenantScoped, TimestampedBase):
    """Logical server set AND the notification unit. A server belongs to exactly
    one group (Server.server_group_id) — no multi-group membership, so threshold
    precedence (PR #2) is simply server > its-group > default."""

    __tablename__ = "server_groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_server_group_name"),)

    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Server(TenantScoped, TimestampedBase):
    __tablename__ = "servers"
    # cmdb_ci is the INVARIANT server identity (unlike instance/hostname). Unique
    # per tenant; nullable for rows created before this column existed.
    __table_args__ = (UniqueConstraint("tenant_id", "cmdb_ci", name="uq_server_cmdb_ci"),)

    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    cmdb_ci: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    labels: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True
    )
    # exactly-one logical/notification group (1:1 membership)
    server_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("server_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
