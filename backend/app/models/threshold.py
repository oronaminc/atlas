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

from sqlalchemy import Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class Comparator(enum.StrEnum):
    gt = ">"  # fires when value is HIGH (e.g. mem used %) -> suppress if value < threshold
    lt = "<"  # fires when value is LOW (e.g. mem available %) -> suppress if value > threshold


class RuleCatalog(TimestampedBase):
    __tablename__ = "rule_catalog"
    __table_args__ = (UniqueConstraint("alertname", name="uq_rule_catalog_alertname"),)

    alertname: Mapped[str] = mapped_column(String(255), index=True)
    # stored as the StrEnum value (">"/"<"); plain VARCHAR for dialect simplicity
    comparator: Mapped[str | None] = mapped_column(String(2), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # PromQL whose result is the current value; {{cmdb_ci}} is substituted at
    # filter time. NULL => threshold filter is a no-op for this alertname.
    value_query: Mapped[str | None] = mapped_column(Text, nullable=True)


class ThresholdOverride(TimestampedBase):
    __tablename__ = "threshold_overrides"
    __table_args__ = (
        UniqueConstraint(
            "alertname",
            "target_cmdb_ci",
            "target_label_key",
            "target_label_value",
            name="uq_threshold_override",
        ),
    )

    alertname: Mapped[str] = mapped_column(String(255), index=True)
    # IMP redesign: label-scoped override target. Precedence at resolve time:
    # target_cmdb_ci > (target_label_key, target_label_value) > none.
    target_cmdb_ci: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    target_label_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_label_value: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    value: Mapped[float] = mapped_column(Float)
