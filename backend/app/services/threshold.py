"""Ingest-time threshold filter (PR #2, Model 2).

Precedence (IMP, label-based — no server table): per-server cmdb_ci override >
label-scoped override (target_label_key matches one of the alert's labels, e.g.
cmdb_service_l2_code) > none = never suppress. For an overridden target we fetch
the CURRENT metric value from Mimir (catalog.value_query with the cmdb_ci
substituted) and suppress the alert iff it's *less severe* than the override.

FAIL-OPEN is absolute: missing cmdb_ci / no override / no catalog value_query /
query error / timeout / empty / non-numeric -> PASS (never suppress). A real
alert must never be dropped because of a lookup hiccup.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import AlertEvent
from app.models.threshold import Comparator, RuleCatalog, ThresholdOverride

# fetch_value(filled_promql) -> current value, or None on any failure
FetchValue = Callable[[str], Awaitable[float | None]]


class ValueCache:
    """Tiny per-(cmdb_ci, alertname) TTL cache so AM resends/dedup don't
    re-hammer Mimir. Caches misses too (None) — still fail-open."""

    def __init__(self, ttl_seconds: float = 10.0) -> None:
        self._ttl = ttl_seconds
        self._d: dict[tuple, tuple[float | None, float]] = {}

    async def get(self, key: tuple, loader: Callable[[], Awaitable[float | None]], now: float):
        hit = self._d.get(key)
        if hit is not None and hit[1] > now:
            return hit[0]
        val = await loader()
        self._d[key] = (val, now + self._ttl)
        return val


def parse_instant_value(resp: dict[str, Any]) -> float | None:
    """Prometheus instant-query JSON -> the first sample's value, or None."""
    try:
        result = resp["data"]["result"]
        if not result:
            return None
        return float(result[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def resolve_threshold(
    db: AsyncSession,
    labels: dict[str, str],
    alertname: str,
) -> tuple[str, float] | None:
    """Label-based precedence (IMP): per-server cmdb_ci override > label-scoped
    override (target_label_key matches a label value, e.g. cmdb_service_l2_code)
    > None (default = never suppress). No server table — everything is matched
    against the alert's own labels."""
    cmdb_ci = labels.get("cmdb_ci")
    if cmdb_ci:
        server_ovr = (
            await db.execute(
                select(ThresholdOverride.value).where(
                    ThresholdOverride.alertname == alertname,
                    ThresholdOverride.target_cmdb_ci == cmdb_ci,
                )
            )
        ).scalar_one_or_none()
        if server_ovr is not None:
            return ("cmdb_ci", server_ovr)

    # label-scoped overrides: first whose (key, value) the alert's labels satisfy
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
    for key, value, threshold in rows:
        if key and labels.get(key) == value:
            return ("label", threshold)
    return None


def _is_below_severity(value: float, threshold: float, comparator: str) -> bool:
    """True => suppress. gt-rule (fires high): suppress when value < threshold.
    lt-rule (fires low): suppress when value > threshold. At exactly the
    threshold the alert still fires (not suppressed)."""
    if comparator == Comparator.gt.value:
        return value < threshold
    if comparator == Comparator.lt.value:
        return value > threshold
    return False  # unknown comparator -> fail-open


async def should_suppress(
    db: AsyncSession,
    event: AlertEvent,
    *,
    fetch_value: FetchValue,
    cache: ValueCache,
    now: float | None = None,
) -> tuple[bool, float | None]:
    """Returns (suppress, fetched_value). Fail-open everywhere."""
    now = now if now is not None else time.monotonic()
    labels = event.labels or {}
    cmdb_ci = labels.get("cmdb_ci")
    if not cmdb_ci:
        return (False, None)

    resolved = await resolve_threshold(db, labels, event.name)
    if resolved is None:
        return (False, None)  # no override -> never suppress
    _tier, threshold = resolved

    catalog = (
        await db.execute(select(RuleCatalog).where(RuleCatalog.alertname == event.name))
    ).scalar_one_or_none()
    if catalog is None or not catalog.value_query or not catalog.comparator:
        return (False, None)  # not configured -> pass-through

    promql = catalog.value_query.replace("{{cmdb_ci}}", cmdb_ci)
    key = (cmdb_ci, event.name)

    async def _load() -> float | None:
        try:
            return await fetch_value(promql)
        except Exception:
            return None  # query error/timeout -> fail-open

    value = await cache.get(key, _load, now)
    if value is None:
        return (False, None)  # empty/non-numeric/error -> fail-open

    return (_is_below_severity(value, threshold, catalog.comparator), value)
