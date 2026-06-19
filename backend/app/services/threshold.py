"""Ingest-time threshold filter (PR #2, Model 2).

Precedence: per-server (cmdb_ci) > the server's single group > default. The
default tier means "no override" -> never suppress. For an overridden target we
fetch the CURRENT metric value from Mimir (catalog.value_query with the cmdb_ci
substituted) and suppress the alert iff it's *less severe* than the override.

FAIL-OPEN is absolute: missing cmdb_ci / no override / no catalog value_query /
query error / timeout / empty / non-numeric -> PASS (never suppress). A real
alert must never be dropped because of a lookup hiccup.
"""

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import AlertEvent
from app.models.server import Server
from app.models.threshold import Comparator, OverrideTier, RuleCatalog, ThresholdOverride

# fetch_value(tenant_id, filled_promql) -> current value, or None on any failure
FetchValue = Callable[[uuid.UUID | None, str], Awaitable[float | None]]


class ValueCache:
    """Tiny per-(tenant, cmdb_ci, alertname) TTL cache so AM resends/dedup don't
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
    db: AsyncSession, tenant_id: uuid.UUID | None, cmdb_ci: str, alertname: str
) -> tuple[str, float] | None:
    """server override > the server's group override > None (default)."""
    server_ovr = (
        await db.execute(
            select(ThresholdOverride.value).where(
                ThresholdOverride.tenant_id == tenant_id,
                ThresholdOverride.alertname == alertname,
                ThresholdOverride.tier == OverrideTier.server.value,
                ThresholdOverride.target_cmdb_ci == cmdb_ci,
            )
        )
    ).scalar_one_or_none()
    if server_ovr is not None:
        return (OverrideTier.server.value, server_ovr)

    group_id = (
        await db.execute(
            select(Server.server_group_id).where(
                Server.tenant_id == tenant_id, Server.cmdb_ci == cmdb_ci
            )
        )
    ).scalar_one_or_none()
    if group_id is not None:
        group_ovr = (
            await db.execute(
                select(ThresholdOverride.value).where(
                    ThresholdOverride.tenant_id == tenant_id,
                    ThresholdOverride.alertname == alertname,
                    ThresholdOverride.tier == OverrideTier.group.value,
                    ThresholdOverride.target_group_id == group_id,
                )
            )
        ).scalar_one_or_none()
        if group_ovr is not None:
            return (OverrideTier.group.value, group_ovr)
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
    cmdb_ci = (event.labels or {}).get("cmdb_ci")
    if not cmdb_ci:
        return (False, None)

    resolved = await resolve_threshold(db, event.tenant_id, cmdb_ci, event.name)
    if resolved is None:
        return (False, None)  # default tier -> never suppress
    _tier, threshold = resolved

    catalog = (
        await db.execute(
            select(RuleCatalog).where(
                RuleCatalog.tenant_id == event.tenant_id, RuleCatalog.alertname == event.name
            )
        )
    ).scalar_one_or_none()
    if catalog is None or not catalog.value_query or not catalog.comparator:
        return (False, None)  # not configured -> pass-through

    promql = catalog.value_query.replace("{{cmdb_ci}}", cmdb_ci)
    key = (event.tenant_id, cmdb_ci, event.name)

    async def _load() -> float | None:
        try:
            return await fetch_value(event.tenant_id, promql)
        except Exception:
            return None  # query error/timeout -> fail-open

    value = await cache.get(key, _load, now)
    if value is None:
        return (False, None)  # empty/non-numeric/error -> fail-open

    return (_is_below_severity(value, threshold, catalog.comparator), value)
