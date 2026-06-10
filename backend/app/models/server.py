import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JsonType, TimestampedBase


class Server(TimestampedBase):
    __tablename__ = "servers"

    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    labels: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True
    )
