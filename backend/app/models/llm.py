"""LLM incident analysis (Feature A).

Per-service config (mirrors notification_settings: tenant_id NULL = platform
default, set = per-service override). api_key Fernet-encrypted like the
telegram bot token. The analysis row IS the async job — claimed CAS+lease by
the llm_worker, so a slow/failing external LLM never blocks the incident
pipeline. Air-gap: base_url defaults empty + enabled=False; nothing is sent
anywhere until an admin explicitly configures an endpoint.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AwareDateTime, TimestampedBase


class LLMConfig(TimestampedBase):
    """OpenAI-compatible endpoint config; one row per service (+ NULL default)."""

    __tablename__ = "llm_config"

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # empty default => no external host hardcoded; self-hosted is the primary path
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted
    model: Mapped[str] = mapped_column(String(200), default="")
    max_prompt_chars: Mapped[int] = mapped_column(Integer, default=12000)
    max_completion_tokens: Mapped[int] = mapped_column(Integer, default=512)
    daily_quota: Mapped[int] = mapped_column(Integer, default=200)
    auto_analyze: Mapped[bool] = mapped_column(Boolean, default=False)
    # stricter redaction (drop unknown labels + cap free-text) when the endpoint
    # is external (not a private/internal host)
    redact_external_strict: Mapped[bool] = mapped_column(Boolean, default=True)


class IncidentAnalysis(TimestampedBase):
    """Job-as-row: pending -> (claim) -> running -> done|failed. One current
    analysis per incident; re-analyze upserts (new prompt_hash on change)."""

    __tablename__ = "incident_analysis"
    __table_args__ = (UniqueConstraint("incident_id", name="uq_incident_analysis"),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending/running/done/failed
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
