"""Threshold-override model (PR #2). Ingest-time per-server / per-group
threshold overrides with precedence server > its-group > default. Compiled
against the live metric VALUE fetched from Mimir at filter time (Model 2);
atlas never modifies Ruler rules.

RuleCatalog carries the per-alertname metadata: which way the comparison runs
(comparator), the unit (display), and the `value_query` (PromQL with a
{{cmdb_ci}} slot) atlas runs to read the current value. value_query NULL =>
not configured => pass-through (the filter can't evaluate, so it never
suppresses)."""

import enum
import uuid

from sqlalchemy import Float, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantScoped, TimestampedBase


class Comparator(enum.StrEnum):
    gt = ">"  # fires when value is HIGH (e.g. mem used %) -> suppress if value < threshold
    lt = "<"  # fires when value is LOW (e.g. mem available %) -> suppress if value > threshold


class OverrideTier(enum.StrEnum):
    server = "server"
    group = "group"


class RuleCatalog(TenantScoped, TimestampedBase):
    __tablename__ = "rule_catalog"
    __table_args__ = (UniqueConstraint("tenant_id", "alertname", name="uq_rule_catalog_alertname"),)

    alertname: Mapped[str] = mapped_column(String(255), index=True)
    # stored as the StrEnum value (">"/"<"); plain VARCHAR for dialect simplicity
    comparator: Mapped[str | None] = mapped_column(String(2), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # PromQL whose result is the current value; {{cmdb_ci}} is substituted at
    # filter time. NULL => threshold filter is a no-op for this alertname.
    value_query: Mapped[str | None] = mapped_column(Text, nullable=True)


class ThresholdOverride(TenantScoped, TimestampedBase):
    __tablename__ = "threshold_overrides"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "alertname",
            "tier",
            "target_cmdb_ci",
            "target_group_id",
            name="uq_threshold_override",
        ),
    )

    alertname: Mapped[str] = mapped_column(String(255), index=True)
    tier: Mapped[str] = mapped_column(String(10), index=True)  # OverrideTier value
    target_cmdb_ci: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    target_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    # IMP redesign: label-scoped override target (replaces server-group tier in a
    # later stage). Precedence at resolve time: target_cmdb_ci > (key,value) > none.
    target_label_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_label_value: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    value: Mapped[float] = mapped_column(Float)
