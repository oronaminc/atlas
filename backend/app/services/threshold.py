"""Ingest-time threshold filter (no PromQL anywhere).

The incident filter decides whether a firing alert is incident-worthy. It NEVER
queries Mimir and never parses PromQL. Inputs are all label/annotation/cache:

- current value  = the alert's carried value (AlertEvent.value, parsed at ingest
  from its annotations).
- effective threshold = per-server (cmdb_ci) override > per-service
  (cmdb_service_l2_code) override > the rule's BASE threshold.
- base threshold + comparator (decision A1) = the alert's OWN annotations
  (atlas_threshold / atlas_compare) preferred, else the cached Mimir rule's
  base (read from the rule's labels/annotations by the sync worker).

FAIL-OPEN is absolute: no value / no comparator / no effective threshold -> PASS
(never suppress). Suppressed alerts are still stored, just not escalated.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import AlertEvent
from app.models.mimir import MimirRule
from app.models.threshold import Comparator, ThresholdOverride

THRESHOLD_KEYS = ("atlas_threshold", "threshold")
COMPARE_KEYS = ("atlas_compare", "atlas_comparator", "compare")
VALUE_KEYS = ("value", "atlas_value")


def to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _first(d: dict[str, Any], keys) -> Any:
    for k in keys:
        if (d or {}).get(k) not in (None, ""):
            return d[k]
    return None


def value_from_annotations(annotations: dict[str, Any]) -> float | None:
    """The metric value the alert carries (set onto AlertEvent.value at ingest)."""
    return to_float(_first(annotations, VALUE_KEYS))


async def resolve_override(
    db: AsyncSession, labels: dict[str, str], alertname: str
) -> float | None:
    """Override number, precedence per-server cmdb_ci > per-service label
    (e.g. cmdb_service_l2_code) > None. Matched against the alert's own labels."""
    cmdb_ci = labels.get("cmdb_ci")
    if cmdb_ci:
        v = (
            await db.execute(
                select(ThresholdOverride.value).where(
                    ThresholdOverride.alertname == alertname,
                    ThresholdOverride.target_cmdb_ci == cmdb_ci,
                )
            )
        ).scalar_one_or_none()
        if v is not None:
            return v
    rows = (
        await db.execute(
            select(
                ThresholdOverride.target_label_key,
                ThresholdOverride.target_label_value,
                ThresholdOverride.value,
            ).where(
                ThresholdOverride.alertname == alertname,
                ThresholdOverride.target_label_key.isnot(None),
            )
        )
    ).all()
    for key, val, threshold in rows:
        if key and labels.get(key) == val:
            return threshold
    return None


async def _base_threshold(
    db: AsyncSession, annotations: dict[str, Any], alertname: str
) -> tuple[float | None, str | None]:
    """Rule base + comparator: the alert's own annotations win; else the cached
    Mimir rule's base (read-only from the rule's labels/annotations)."""
    base = to_float(_first(annotations, THRESHOLD_KEYS))
    cmp_raw = _first(annotations, COMPARE_KEYS)
    comparator = cmp_raw if cmp_raw in (">", "<") else None
    if base is not None and comparator is not None:
        return base, comparator
    rule = (
        await db.execute(select(MimirRule).where(MimirRule.alertname == alertname).limit(1))
    ).scalar_one_or_none()
    if rule is not None:
        if base is None:
            base = rule.base_threshold
        if comparator is None:
            comparator = rule.comparator
    return base, comparator


def _is_below_severity(value: float, threshold: float, comparator: str) -> bool:
    """True => suppress. gt-rule (fires high): suppress when value < threshold.
    lt-rule (fires low): suppress when value > threshold. At exactly the
    threshold the alert still fires (not suppressed)."""
    if comparator == Comparator.gt.value:
        return value < threshold
    if comparator == Comparator.lt.value:
        return value > threshold
    return False


async def should_suppress(db: AsyncSession, event: AlertEvent) -> tuple[bool, float | None]:
    """Returns (suppress, value). Fail-open everywhere. No Mimir query, no PromQL."""
    labels = event.labels or {}
    annotations = event.annotations or {}
    value = event.value if event.value is not None else value_from_annotations(annotations)
    if value is None:
        return (False, None)

    base, comparator = await _base_threshold(db, annotations, event.name)
    if comparator is None:
        return (False, value)
    override = await resolve_override(db, labels, event.name)
    effective = override if override is not None else base
    if effective is None:
        return (False, value)
    return (_is_below_severity(value, effective, comparator), value)
