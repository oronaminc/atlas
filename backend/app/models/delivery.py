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

from app.models.base import AwareDateTime, JsonType, TenantScoped, TimestampedBase


class Notification(TenantScoped, TimestampedBase):
    """Outbox row = persisted send intent. Created before any side effect;
    claimed via CAS+lease; at-least-once delivery."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "incident_id", "channel", "recipient_user_id", name="uq_notification_target"
        ),
        Index("ix_notifications_status_retry", "status", "retry_at"),
        Index("ix_notifications_tenant_status_created", "tenant_id", "status", "created_at"),
        # Phase 4 claim index. Migration 0007 redefines this as a PARTIAL index
        # WHERE status IN ('pending','failed') on PG — that's what turns the
        # claim from an 861ms seq-scan+sort into an index-ordered scan. Declared
        # plain here so SQLite/metadata create_all matches; the partial-ness is
        # a PG storage detail the ORM never needs to know.
        Index("ix_notifications_claim", "tenant_id", "priority", "created_at"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(50))
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
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


class NotificationRoute(TenantScoped, TimestampedBase):
    """Per-group send config: one route per group."""

    __tablename__ = "notification_routes"
    __table_args__ = (UniqueConstraint("group_id", name="uq_notification_route_group"),)

    group_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("groups.id", ondelete="CASCADE"))
    min_severity: Mapped[str] = mapped_column(String(20), default="warning")
    channels: Mapped[list[str]] = mapped_column(JsonType, default=lambda: ["telegram"])
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class NotificationSettings(TenantScoped, TimestampedBase):
    """Single row: bot token (Fernet-encrypted), rate limit, quotas."""

    __tablename__ = "notification_settings"

    telegram_bot_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_rate_per_second: Mapped[int] = mapped_column(Integer, default=25)
    quota_group_per_hour: Mapped[int] = mapped_column(Integer, default=30)
    quota_global_per_day: Mapped[int] = mapped_column(Integer, default=500)
    # Phase 5: per-service pending-queue alarm threshold (alert, never shed).
    # Breach -> atlas_tenant_pending_softcap_breached{service=slug}=1 at scrape.
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


class NotificationMute(TenantScoped, TimestampedBase):
    """atlas-side notification mute by (target x alertname), with wildcards.
    Evaluated at fan-out — orthogonal to AM `Silence` (time-window) and to the
    manual per-incident suppress. NULL alertname = all rules; target_type 'all'
    = every target. Distinct from threshold suppression (PR #2)."""

    __tablename__ = "notification_mutes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "target_type",
            "target_cmdb_ci",
            "target_group_id",
            "alertname",
            name="uq_notification_mute",
        ),
    )

    # 'server' -> target_cmdb_ci, 'group' -> target_group_id, 'all' -> any target
    target_type: Mapped[str] = mapped_column(String(10), default="server", index=True)
    target_cmdb_ci: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    target_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("server_groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # NULL = mute ALL alertnames for the target
    alertname: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
