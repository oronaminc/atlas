"""Mimir read-cache (IMP overhaul): rules + silences synced from Mimir into atlas
by the mimir_sync worker so the UI/threshold filter read a local snapshot instead
of hitting Mimir per request. All read-only mirrors — atlas never authors PromQL;
silence WRITES go straight to Alertmanager and the next sync reflects them.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AwareDateTime, JsonType, TimestampedBase


class MimirRule(TimestampedBase):
    """One alerting rule pulled from the Mimir rules API (config + eval state).
    base_threshold/comparator are extracted read-only from the rule's own
    labels/annotations (atlas_threshold / atlas_compare) — the threshold filter's
    fallback when a firing alert doesn't carry its own value/threshold."""

    __tablename__ = "mimir_rules"
    __table_args__ = (
        UniqueConstraint("namespace", "group_name", "alertname", name="uq_mimir_rule"),
    )

    alertname: Mapped[str] = mapped_column(String(255), index=True)
    group_name: Mapped[str] = mapped_column(String(255), default="")
    namespace: Mapped[str] = mapped_column(String(255), default="")
    expr: Mapped[str] = mapped_column(Text, default="")
    for_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    labels: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    # eval state from the Prometheus rules API (how it's collected + failures)
    health: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ok|err|unknown
    state: Mapped[str | None] = mapped_column(String(20), nullable=True)  # inactive|pending|firing
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_evaluation: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # representative read value
    # atlas threshold base (read-only, from the rule's labels/annotations)
    base_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    comparator: Mapped[str | None] = mapped_column(String(2), nullable=True)  # ">" | "<"
    synced_at: Mapped[datetime] = mapped_column(AwareDateTime())


class MimirSilence(TimestampedBase):
    """A silence mirrored from the Mimir Alertmanager (read cache). Writes go
    directly to AM; the next sync upserts the result here."""

    __tablename__ = "mimir_silences"
    __table_args__ = (UniqueConstraint("silence_id", name="uq_mimir_silence"),)

    silence_id: Mapped[str] = mapped_column(String(255), index=True)
    matchers: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    starts_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str | None] = mapped_column(String(20), nullable=True)  # active|pending|expired
    synced_at: Mapped[datetime] = mapped_column(AwareDateTime())


class MimirQueryConfig(TimestampedBase):
    """Single row, admin-managed. Bounds the Mimir label-discovery proxy: when a
    label query omits start/end, atlas defaults to [now - lookback, now] so a
    stale bucket-index / full-retention window can't 422 the whole query.
    DB value is authoritative; 1h is the seeded/fallback default."""

    __tablename__ = "mimir_query_config"

    label_query_lookback_hours: Mapped[int] = mapped_column(Integer, default=1)
