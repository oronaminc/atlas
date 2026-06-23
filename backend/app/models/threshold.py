"""Threshold-override model. Per-server (cmdb_ci) / per-service (label) overrides
of an alert rule's threshold, applied by the ingest filter to decide whether a
firing alert is incident-worthy. No PromQL: the comparison uses the alert's own
carried value vs the effective threshold (override > rule base). Precedence:
target_cmdb_ci > (target_label_key, target_label_value) > the rule base."""

import enum

from sqlalchemy import Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class Comparator(enum.StrEnum):
    gt = ">"  # fires when value is HIGH (e.g. mem used %) -> suppress if value < threshold
    lt = "<"  # fires when value is LOW (e.g. mem available %) -> suppress if value > threshold


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
