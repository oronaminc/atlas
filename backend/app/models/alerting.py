"""Correlation engine storage: normalized alert history, incidents, timeline,
and DB-backed engine config."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import JsonType, TenantScoped, TimestampedBase


class IncidentStatus(enum.StrEnum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"
    # explicit mute: hidden from active views, keeps absorbing matching
    # alerts without re-notifying; reversible via unsuppress (-> open)
    suppressed = "suppressed"


class AlertEvent(TenantScoped, TimestampedBase):
    __tablename__ = "alert_events"
    __table_args__ = (
        Index("ix_alert_events_fp_received", "fingerprint", "received_at"),
        Index("ix_alert_events_tenant_received", "tenant_id", "received_at"),
    )

    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(20), default="info")
    status: Mapped[str] = mapped_column(String(20), default="firing")
    labels: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    dedup_count: Mapped[int] = mapped_column(Integer, default=1)
    # Value fetched from Mimir by the ingest-time threshold filter (PR #2);
    # recorded for audit (e.g. "suppressed: 92 < 95"). NULL = never evaluated.
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Terminal flag: threshold filter dropped this event below the effective
    # override -> stored but NOT escalated to an incident, and excluded from
    # re-claim (incident_id stays NULL).
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    incident: Mapped["Incident | None"] = relationship(back_populates="alerts")


class Incident(TenantScoped, TimestampedBase):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_group_key_last_seen", "group_key", "last_seen"),
        Index("ix_incidents_tenant_last_seen", "tenant_id", "last_seen"),
    )

    title: Mapped[str] = mapped_column(String(500))
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status"),
        default=IncidentStatus.open,
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(20), default="info")
    group_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    alert_count: Mapped[int] = mapped_column(Integer, default=0)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    alerts: Mapped[list[AlertEvent]] = relationship(back_populates="incident")
    timeline: Mapped[list["IncidentEvent"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentEvent.created_at",
    )


class IncidentEvent(TenantScoped, TimestampedBase):
    """Timeline entry: created / alert_attached / status_changed / comment."""

    __tablename__ = "incident_events"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

    incident: Mapped[Incident] = relationship(back_populates="timeline")


class CorrelationConfig(TimestampedBase):
    """Single-row engine config, editable from the admin UI."""

    __tablename__ = "correlation_config"

    dedup_window_seconds: Mapped[int] = mapped_column(Integer, default=300)
    correlation_window_seconds: Mapped[int] = mapped_column(Integer, default=900)
    group_attrs: Mapped[list[str]] = mapped_column(
        JsonType, default=lambda: ["host", "service", "cluster"]
    )
