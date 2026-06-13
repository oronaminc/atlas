"""Retention policy (single admin row) + hourly alert rollups.

alert_stats_hourly feeds /stats/trend + alerts_24h so the dashboards stop
scanning the raw 24h alert_events slice (Phase 1: 810ms p50 @ 357k rows).
Rows are replaced idempotently (DELETE+INSERT per hour window) — no
ON CONFLICT, so NULL tenant_id (legacy rows) stays portable across PG/SQLite.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantScoped, TimestampedBase


class RetentionConfig(TimestampedBase):
    """Single row, HQ-admin managed; days per data class. 0 = keep forever."""

    __tablename__ = "retention_config"

    alert_events_days: Mapped[int] = mapped_column(Integer, default=90)
    incidents_days: Mapped[int] = mapped_column(Integer, default=180)
    notifications_days: Mapped[int] = mapped_column(Integer, default=90)
    audit_days: Mapped[int] = mapped_column(Integer, default=365)
    archive_enabled: Mapped[bool] = mapped_column(default=False)


class AlertStatsHourly(TenantScoped, TimestampedBase):
    """Closed-hour alert counts: (tenant, bucket_start, severity) -> count.
    TenantScoped so the choke point auto-filters dashboard reads."""

    __tablename__ = "alert_stats_hourly"
    __table_args__ = (
        Index("ix_alert_stats_hourly_bucket", "bucket_start"),
        Index("ix_alert_stats_hourly_tenant_bucket", "tenant_id", "bucket_start"),
    )

    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    severity: Mapped[str] = mapped_column(String(20))
    count: Mapped[int] = mapped_column(Integer, default=0)
