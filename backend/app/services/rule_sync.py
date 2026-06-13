"""Serializes DB rule groups to Prometheus rule-group YAML and pushes them to
the Mimir Ruler. The DB is the source of truth; checksums avoid no-op PUTs."""

import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AlertRule, RuleGroup, SyncState
from app.models.base import utcnow
from app.models.sync import SyncStatus, SyncTarget

logger = logging.getLogger(__name__)


def serialize_rule(rule: AlertRule) -> dict[str, Any]:
    labels = {**(rule.labels or {}), "severity": rule.severity.value}
    payload: dict[str, Any] = {
        "alert": rule.name,
        "expr": rule.expr,
        "for": rule.for_duration,
        "labels": labels,
    }
    if rule.annotations:
        payload["annotations"] = rule.annotations
    return payload


def serialize_rule_group(group: RuleGroup) -> dict[str, Any]:
    rules = [
        serialize_rule(link.rule)
        for link in sorted(group.rule_links, key=lambda link: link.order)
        if link.rule.enabled
    ]
    return {
        "name": group.name,
        "interval": group.interval,
        "rules": rules,
    }


def payload_checksum(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def get_or_create_sync_state(db: AsyncSession, target: SyncTarget) -> SyncState:
    res = await db.execute(select(SyncState).where(SyncState.target == target))
    state = res.scalar_one_or_none()
    if state is None:
        state = SyncState(target=target, status=SyncStatus.pending)
        db.add(state)
        await db.flush()
    return state


async def org_for_tenant(db: AsyncSession, tenant_id) -> str | None:
    """First mapped Mimir org for a tenant (rule groups push under it)."""
    if tenant_id is None:
        return None
    from app.models.tenant import MimirOrgMap

    return (
        await db.execute(
            select(MimirOrgMap.mimir_org)
            .where(MimirOrgMap.tenant_id == tenant_id)
            .order_by(MimirOrgMap.mimir_org)
            .limit(1)
        )
    ).scalar_one_or_none()


async def sync_all_rule_groups(db: AsyncSession, ruler: Any, ruler_factory=None) -> SyncState:
    """Pushes every rule group to the ruler under its tenant's Mimir org.
    `ruler` is the default-org MimirRulerClient (typed as Any so tests can
    pass fakes); `ruler_factory(org)` builds per-org clients — when None,
    everything goes through `ruler` (legacy/single-org behavior)."""
    state = await get_or_create_sync_state(db, SyncTarget.ruler)
    res = await db.execute(select(RuleGroup))
    groups = list(res.scalars().unique())

    orgs = {(g.namespace, g.name): await org_for_tenant(db, g.tenant_id) for g in groups}
    payloads = {(g.namespace, g.name): serialize_rule_group(g) for g in groups}
    checksum = payload_checksum(
        sorted((ns, name, json.dumps(p, sort_keys=True)) for (ns, name), p in payloads.items())
    )

    if state.checksum == checksum and state.status == SyncStatus.ok:
        return state

    try:
        clients: dict[str, Any] = {}
        for (namespace, name), payload in payloads.items():
            org = orgs.get((namespace, name))
            client = ruler
            if ruler_factory is not None and org and org != getattr(ruler, "org", None):
                if org not in clients:
                    clients[org] = ruler_factory(org)
                client = clients[org]
            await client.set_rule_group(namespace, payload)
        state.status = SyncStatus.ok
        state.last_error = None
        state.last_synced_at = utcnow()
        state.checksum = checksum
    except Exception as exc:
        logger.exception("ruler sync failed")
        state.status = SyncStatus.failed
        state.last_error = str(exc)[:2000]
    await db.flush()
    return state


async def sync_one_rule_group(
    db: AsyncSession, ruler: Any, group: RuleGroup, ruler_factory=None
) -> None:
    payload = serialize_rule_group(group)
    org = await org_for_tenant(db, group.tenant_id)
    if ruler_factory is not None and org and org != getattr(ruler, "org", None):
        ruler = ruler_factory(org)
    await ruler.set_rule_group(group.namespace, payload)


async def mark_ruler_pending(db: AsyncSession) -> None:
    """Called after any rule/rule-group mutation so the worker picks it up."""
    state = await get_or_create_sync_state(db, SyncTarget.ruler)
    if state.status != SyncStatus.failed:
        state.status = SyncStatus.pending
    state.checksum = None
    await db.flush()


def emergency_group_payload(rule: AlertRule) -> tuple[str, dict[str, Any]]:
    """Single-rule group for emergency apply: pushed to a dedicated namespace
    so it cannot clobber managed groups."""
    namespace = "emergency"
    payload = {
        "name": f"emergency-{rule.id}",
        "interval": "1m",
        "rules": [serialize_rule(rule)],
    }
    return namespace, payload


async def find_groups_containing_rule(db: AsyncSession, rule_id: uuid.UUID) -> list[RuleGroup]:
    from app.models import RuleGroupRule

    res = await db.execute(
        select(RuleGroup)
        .join(RuleGroupRule, RuleGroupRule.rule_group_id == RuleGroup.id)
        .where(RuleGroupRule.alert_rule_id == rule_id)
    )
    return list(res.scalars().unique())
