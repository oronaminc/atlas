"""Notification delivery: outbox + settings/defaults (admin-managed)."""

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
        UniqueConstraint(
            "incident_id", "channel", "recipient_user_id", name="uq_notification_target"
        ),
        Index("ix_notifications_status_retry", "status", "retry_at"),
        # Phase 4 claim index. The baseline migration redefines this as a PARTIAL
        # index WHERE status IN ('pending','failed') on PG — that's what turns the
        # claim from an 861ms seq-scan+sort into an index-ordered scan. Declared
        # plain here so SQLite/metadata create_all matches; the partial-ness is
        # a PG storage detail the ORM never needs to know.
        Index("ix_notifications_claim", "priority", "created_at"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(50))
    # nullable: an OnCall (team-webhook) notification has no per-user recipient
    # (IMP §7/J) — one row per incident, recipient_user_id NULL.
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    recipient_address: Mapped[str] = mapped_column(String(255))  # chat_id / email snapshot
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # send priority, lower = sooner; derived from incident severity at fan-out
    # (critical=0, warning=1, info=2). Claim orders by (priority, created_at).
    priority: Mapped[int] = mapped_column(Integer, default=1)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    incident = relationship("Incident", lazy="joined")


class NotificationSettings(TimestampedBase):
    """Single row: bot token (Fernet-encrypted), rate limit, quotas."""

    __tablename__ = "notification_settings"

    telegram_bot_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_rate_per_second: Mapped[int] = mapped_column(Integer, default=25)
    quota_group_per_hour: Mapped[int] = mapped_column(Integer, default=30)
    quota_global_per_day: Mapped[int] = mapped_column(Integer, default=500)
    # Phase 5: pending-queue alarm threshold (alert, never shed).
    # Breach -> atlas_pending_softcap_breached=1 at scrape.
    pending_softcap: Mapped[int] = mapped_column(Integer, default=50000)
    # IMP redesign §7/J: OnCall = a team webhook (not per-user). Token Fernet-
    # encrypted at the service layer like telegram_bot_token.
    oncall_webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    oncall_token: Mapped[str | None] = mapped_column(Text, nullable=True)


class NotificationDefault(TimestampedBase):
    """IMP redesign §7: admin-managed default channel toggles applied to each new
    incident at creation. Single row."""

    __tablename__ = "notification_defaults"

    default_email: Mapped[bool] = mapped_column(Boolean, default=True)
    default_telegram: Mapped[bool] = mapped_column(Boolean, default=True)
    default_oncall: Mapped[bool] = mapped_column(Boolean, default=False)
