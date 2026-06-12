import uuid
from typing import Any

from sqlalchemy import Boolean, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JsonType, TimestampedBase


class AuditLog(TimestampedBase):
    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(100), index=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, index=True
    )
    before: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    emergency: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
