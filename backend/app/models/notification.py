import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JsonType, TenantScoped, TimestampedBase


class ReceiverType(enum.StrEnum):
    slack = "slack"
    email = "email"
    webhook = "webhook"
    pagerduty = "pagerduty"


class Receiver(TenantScoped, TimestampedBase):
    __tablename__ = "receivers"

    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    type: Mapped[ReceiverType] = mapped_column(Enum(ReceiverType, name="receiver_type"))
    # Secret values inside config are Fernet-encrypted before persisting.
    config: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class NotificationPolicy(TenantScoped, TimestampedBase):
    __tablename__ = "notification_policies"

    matcher: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    receiver_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("receivers.id", ondelete="CASCADE"), index=True
    )
    group_by: Mapped[list[str]] = mapped_column(JsonType, default=list)
    repeat_interval: Mapped[str] = mapped_column(String(20), default="4h")


class Silence(TenantScoped, TimestampedBase):
    __tablename__ = "silences"

    matchers: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str] = mapped_column(Text, default="")
    # Alertmanager-side silence id once synced.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
