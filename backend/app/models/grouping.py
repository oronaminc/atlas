"""Topology grouping criteria for the correlation engine (IMP redesign).

Replaces the old single-row CorrelationConfig. The schema can hold MANY rules
(priority-ordered, optional `match` label-predicates, compound `label_keys`)
but v1 ships exactly ONE editable rule: group by cmdb_service_l2_code.

Severity-aware formation (decision C): an incident auto-forms when the number
of free in-window alerts sharing the topology key reaches the effective
threshold — `1` for a critical alert when `critical_immediate` is set (a single
critical is immediately a sit incident), else `min_group_size` (default 2 for
warning/info). Manual promote bypasses this entirely.
"""

from typing import Any

from sqlalchemy import Boolean, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JsonType, TimestampedBase


class GroupingRule(TimestampedBase):
    __tablename__ = "grouping_rules"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # higher priority wins when multiple rules match an alert (v1: single rule)
    priority: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    # ordered compound topology key (v1 default: ["cmdb_service_l2_code"])
    label_keys: Mapped[list[str]] = mapped_column(
        JsonType, default=lambda: ["cmdb_service_l2_code"]
    )
    # optional label predicates scoping the rule to a subset of alerts
    # (reserved for multi-rule v2; NULL = applies to all)
    match: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    window_seconds: Mapped[int] = mapped_column(Integer, default=900, server_default="900")
    # non-critical threshold; critical uses 1 when critical_immediate is set
    min_group_size: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    critical_immediate: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    dedup_window_seconds: Mapped[int] = mapped_column(Integer, default=300, server_default="300")

    def threshold_for(self, severity: str) -> int:
        """Effective min group size for an alert of this severity."""
        if self.critical_immediate and severity == "critical":
            return 1
        return self.min_group_size
