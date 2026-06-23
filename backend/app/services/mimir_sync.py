"""Mimir → atlas read-cache sync (IMP overhaul backbone).

Periodically pulls the Mimir rules (config + eval state) and Alertmanager
silences into atlas cache tables so the UI + threshold filter read a local
snapshot. Idempotent DELETE+INSERT (the sets are small, bounded by the infra's
rule/silence count). atlas authors no PromQL — base thresholds are read from the
rule's own labels/annotations only.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.mimir import MimirQueryConfig, MimirRule, MimirSilence

logger = logging.getLogger(__name__)

# label/annotation keys a rule author sets so atlas knows the base threshold
# without parsing PromQL (decision A1 fallback source).
THRESHOLD_KEYS = ("atlas_threshold", "threshold")
COMPARE_KEYS = ("atlas_compare", "atlas_comparator", "compare")


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _first(d: dict[str, Any], keys) -> Any:
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def extract_threshold(
    labels: dict[str, Any], annotations: dict[str, Any]
) -> tuple[float | None, str | None]:
    """Base threshold + comparator from a rule's own labels/annotations.
    annotations win over labels; absent -> (None, None) (filter fails open)."""
    base = _to_float(_first(annotations, THRESHOLD_KEYS)) or _to_float(
        _first(labels, THRESHOLD_KEYS)
    )
    cmp_raw = _first(annotations, COMPARE_KEYS) or _first(labels, COMPARE_KEYS)
    comparator = cmp_raw if cmp_raw in (">", "<") else None
    return base, comparator


def _parse_dt(s: Any) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _rule_value(rule: dict[str, Any]) -> float | None:
    """Representative read value: max over the rule's active alert instances."""
    vals = [_to_float(a.get("value")) for a in (rule.get("alerts") or [])]
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


async def sync_rules(db: AsyncSession, query_client) -> int:
    """Pull alerting rules (config + eval state) into mimir_rules. Returns count."""
    rules = await query_client.alerting_rules()
    now = utcnow()
    await db.execute(delete(MimirRule))
    seen: set[tuple[str, str, str]] = set()
    n = 0
    for r in rules:
        namespace = str(r.get("_namespace", ""))
        group = str(r.get("_group", ""))
        alertname = str(r.get("name", ""))
        key = (namespace, group, alertname)
        if not alertname or key in seen:
            continue
        seen.add(key)
        labels = r.get("labels", {}) or {}
        annotations = r.get("annotations", {}) or {}
        base, comparator = extract_threshold(labels, annotations)
        duration = r.get("duration")
        db.add(
            MimirRule(
                alertname=alertname,
                group_name=group,
                namespace=namespace,
                expr=r.get("query", "") or "",
                for_seconds=int(duration) if isinstance(duration, (int, float)) else None,
                severity=labels.get("severity"),
                labels=labels,
                annotations=annotations,
                health=r.get("health"),
                state=r.get("state"),
                last_error=r.get("lastError") or None,
                last_evaluation=_parse_dt(r.get("lastEvaluation")),
                value=_rule_value(r),
                base_threshold=base,
                comparator=comparator,
                synced_at=now,
            )
        )
        n += 1
    await db.flush()
    return n


async def sync_silences(db: AsyncSession, am_client) -> int:
    """Pull Alertmanager silences into mimir_silences. Returns count."""
    silences = await am_client.get_silences()
    now = utcnow()
    await db.execute(delete(MimirSilence))
    seen: set[str] = set()
    n = 0
    for s in silences or []:
        sid = str(s.get("id", ""))
        if not sid or sid in seen:
            continue
        seen.add(sid)
        db.add(
            MimirSilence(
                silence_id=sid,
                matchers=s.get("matchers", []) or [],
                starts_at=_parse_dt(s.get("startsAt")),
                ends_at=_parse_dt(s.get("endsAt")),
                comment=s.get("comment"),
                created_by_label=s.get("createdBy"),
                state=(s.get("status") or {}).get("state"),
                synced_at=now,
            )
        )
        n += 1
    await db.flush()
    return n


async def get_mimir_query_config(db: AsyncSession) -> MimirQueryConfig:
    """Single-row admin config for the label-discovery proxy; seeds the default
    (label_query_lookback_hours=1) on first access. DB value is authoritative."""
    row = (await db.execute(select(MimirQueryConfig).limit(1))).scalar_one_or_none()
    if row is None:
        row = MimirQueryConfig()  # label_query_lookback_hours defaults to 1
        db.add(row)
        await db.flush()
    return row
