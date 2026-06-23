"""Notification delivery: outbox + per-group channel config + defaults.

All channels are PER-GROUP (no global bot/webhook): each user group owns its own
telegram bot+chats, email address(es), and oncall webhook. Fanout routes an
incident -> the groups mapped to its l2 -> each group's own configured channels.
"""

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

from app.models.base import AwareDateTime, TimestampedBase


class Notification(TimestampedBase):
    """Outbox row = persisted send intent. Created before any side effect;
    claimed via CAS+lease; at-least-once delivery."""

    __tablename__ = "notifications"
    __table_args__ = (
        # one row per (incident, channel, destination). Group channels have no
        # user -> dedup on the destination address (chat_id / email / oncall ref).
        UniqueConstraint(
            "incident_id", "channel", "recipient_address", name="uq_notification_target"
        ),
        Index("ix_notifications_status_retry", "status", "retry_at"),
        # Phase 4 claim index — partial WHERE status IN ('pending','failed') on PG
        # (the baseline migration redefines it); plain here for SQLite parity.
        Index("ix_notifications_claim", "priority", "created_at"),
    )

    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel: Mapped[str] = mapped_column(String(50))
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    recipient_address: Mapped[str] = mapped_column(String(255))  # chat_id / email / oncall ref
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # which per-group channel config to send through (carries the bot token /
    # webhook url). NULL if the channel was removed after enqueue.
    group_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("group_channels.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    priority: Mapped[int] = mapped_column(Integer, default=1)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    incident = relationship("Incident", lazy="joined")


class GroupChannel(TimestampedBase):
    """One destination a user group sends to. Channel-typed:
    - telegram: bot_token (Fernet) + chat_id   (a group may have N telegram rows)
    - email:    email address
    - oncall:   webhook_url (Fernet) + optional oncall_token (Fernet) bearer
    Secrets are Fernet-encrypted at the service layer and MASKED in responses."""

    __tablename__ = "group_channels"

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(20))  # telegram | email | oncall
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    bot_token: Mapped[str | None] = mapped_column(Text, nullable=True)  # telegram (Fernet)
    chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # telegram
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)  # email
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # oncall (Fernet)
    oncall_token: Mapped[str | None] = mapped_column(Text, nullable=True)  # oncall bearer (Fernet)


class NotificationDefault(TimestampedBase):
    """IMP redesign §7: admin-managed default channel toggles applied to each new
    incident at creation. Single row."""

    __tablename__ = "notification_defaults"

    default_email: Mapped[bool] = mapped_column(Boolean, default=True)
    default_telegram: Mapped[bool] = mapped_column(Boolean, default=True)
    default_oncall: Mapped[bool] = mapped_column(Boolean, default=False)
