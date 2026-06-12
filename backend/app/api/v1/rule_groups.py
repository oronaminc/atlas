import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.rules import get_ruler_client
from app.core.deps import client_ip, get_current_user, require_editor
from app.core.envelope import envelope
from app.core.pagination import decode_cursor, page_meta
from app.db import get_db
from app.models import AlertRule, RuleGroup, RuleGroupRule, User
from app.models.base import utcnow
from app.models.sync import SyncStatus, SyncTarget
from app.schemas.rule import (
    AlertRuleOut,
    RuleGroupCreate,
    RuleGroupOut,
    RuleGroupUpdate,
)
from app.services.audit import record_audit, snapshot
from app.services.rule_sync import (
    get_or_create_sync_state,
    mark_ruler_pending,
    sync_one_rule_group,
)

router = APIRouter(prefix="/rule-groups", tags=["rule-groups"])

GROUP_AUDIT_FIELDS = ["name", "namespace", "interval", "tenant"]


async def load_group(db: AsyncSession, group_id: uuid.UUID) -> RuleGroup | None:
    """Loads a rule group with its links and rules eagerly (async-safe)."""
    res = await db.execute(
        select(RuleGroup)
        .options(selectinload(RuleGroup.rule_links).joinedload(RuleGroupRule.rule))
        .where(RuleGroup.id == group_id)
    )
    return res.scalars().unique().one_or_none()


def group_out(group: RuleGroup, include_rules: bool = False) -> dict:
    out = RuleGroupOut.model_validate(group)
    out.rule_count = len(group.rule_links)
    if include_rules:
        out.rules = [AlertRuleOut.model_validate(link.rule) for link in group.rule_links]
    return out.model_dump(mode="json")


async def _set_group_rules(db: AsyncSession, group: RuleGroup, rule_ids: list[uuid.UUID]) -> None:
    res = await db.execute(select(AlertRule).where(AlertRule.id.in_(rule_ids)))
    found = {r.id for r in res.scalars()}
    missing = [str(rid) for rid in rule_ids if rid not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown rule ids: {missing}")
    await db.execute(delete(RuleGroupRule).where(RuleGroupRule.rule_group_id == group.id))
    await db.flush()
    for order, rid in enumerate(rule_ids):
        db.add(RuleGroupRule(rule_group_id=group.id, alert_rule_id=rid, order=order))
    await db.flush()


@router.get("")
async def list_rule_groups(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(RuleGroup).order_by(RuleGroup.created_at.desc(), RuleGroup.id.desc())
    if q:
        stmt = stmt.where(or_(RuleGroup.name.ilike(f"%{q}%"), RuleGroup.namespace.ilike(f"%{q}%")))
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            t, i = decoded
            stmt = stmt.where(
                or_(
                    RuleGroup.created_at < t,
                    (RuleGroup.created_at == t) & (RuleGroup.id < i),
                )
            )
    res = await db.execute(stmt.limit(limit + 1))
    items, meta = page_meta(list(res.scalars().unique()), limit)
    return envelope([group_out(g) for g in items], meta=meta)


@router.post("", status_code=201)
async def create_rule_group(
    body: RuleGroupCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    dup = await db.execute(
        select(RuleGroup).where(RuleGroup.namespace == body.namespace, RuleGroup.name == body.name)
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Rule group already exists in namespace")
    group = RuleGroup(
        name=body.name,
        namespace=body.namespace,
        interval=body.interval,
        created_by=user.id,
    )
    db.add(group)
    await db.flush()
    if body.rule_ids:
        await _set_group_rules(db, group, body.rule_ids)
    await record_audit(
        db,
        actor_id=user.id,
        action="create",
        resource_type="rule_group",
        resource_id=group.id,
        after=snapshot(group, GROUP_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await mark_ruler_pending(db)
    await db.commit()
    group = await load_group(db, group.id)
    return envelope(group_out(group, include_rules=True))


@router.get("/{group_id}")
async def get_rule_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    group = await load_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Rule group not found")
    return envelope(group_out(group, include_rules=True))


@router.patch("/{group_id}")
async def update_rule_group(
    group_id: uuid.UUID,
    body: RuleGroupUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    group = await load_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Rule group not found")
    before = snapshot(group, GROUP_AUDIT_FIELDS)
    update_data = body.model_dump(exclude_unset=True)
    rule_ids = update_data.pop("rule_ids", None)
    for field, value in update_data.items():
        setattr(group, field, value)
    if rule_ids is not None:
        await _set_group_rules(db, group, rule_ids)
    group.updated_by = user.id
    await record_audit(
        db,
        actor_id=user.id,
        action="update",
        resource_type="rule_group",
        resource_id=group.id,
        before=before,
        after=snapshot(group, GROUP_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await mark_ruler_pending(db)
    await db.commit()
    group = await load_group(db, group_id)
    return envelope(group_out(group, include_rules=True))


@router.delete("/{group_id}")
async def delete_rule_group(
    group_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
    ruler=Depends(get_ruler_client),
):
    group = await load_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Rule group not found")
    before = snapshot(group, GROUP_AUDIT_FIELDS)
    namespace, name = group.namespace, group.name
    await db.delete(group)
    await record_audit(
        db,
        actor_id=user.id,
        action="delete",
        resource_type="rule_group",
        resource_id=group_id,
        before=before,
        ip=client_ip(request),
    )
    await db.commit()
    # Best effort removal from the ruler; the periodic sync reconciles failures.
    try:
        await ruler.delete_rule_group(namespace, name)
    except Exception:
        pass
    return envelope({"ok": True})


@router.post("/{group_id}/sync")
async def sync_rule_group(
    group_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
    ruler=Depends(get_ruler_client),
):
    """Pushes this rule group to the Mimir Ruler immediately
    (X-Scope-OrgID header is injected by the client)."""
    group = await load_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Rule group not found")
    state = await get_or_create_sync_state(db, SyncTarget.ruler)
    try:
        await sync_one_rule_group(db, ruler, group)
        state.status = SyncStatus.ok
        state.last_error = None
        state.last_synced_at = utcnow()
    except Exception as exc:
        state.status = SyncStatus.failed
        state.last_error = str(exc)[:2000]
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Ruler sync failed: {exc}") from exc
    await record_audit(
        db,
        actor_id=user.id,
        action="sync",
        resource_type="rule_group",
        resource_id=group.id,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True, "synced_at": state.last_synced_at.isoformat()})
