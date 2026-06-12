"""Notification delivery: outbox, routes, settings (admin-managed)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AwareDateTime, JsonType, TimestampedBase


class Notification(TimestampedBase):
    """Outbox row = persisted send intent. Created before any side effect;
    claimed via CAS+lease; at-least-once delivery."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "incident_id", "channel", "recipient_user_id", name="uq_notification_target"
        ),
        Index("ix_notifications_status_retry", "status", "retry_at"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(50))
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    recipient_address: Mapped[str] = mapped_column(
        String(255)
    )  # chat_id / email snapshot
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    incident = relationship("Incident", lazy="joined")


class NotificationRoute(TimestampedBase):
    """Per-group send config: one route per group."""

    __tablename__ = "notification_routes"
    __table_args__ = (UniqueConstraint("group_id", name="uq_notification_route_group"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="CASCADE")
    )
    min_severity: Mapped[str] = mapped_column(String(20), default="warning")
    channels: Mapped[list[str]] = mapped_column(JsonType, default=lambda: ["telegram"])
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class NotificationSettings(TimestampedBase):
    """Single row: bot token (Fernet-encrypted), rate limit, quotas."""

    __tablename__ = "notification_settings"

    telegram_bot_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_rate_per_second: Mapped[int] = mapped_column(Integer, default=25)
    quota_group_per_hour: Mapped[int] = mapped_column(Integer, default=30)
    quota_global_per_day: Mapped[int] = mapped_column(Integer, default=500)
