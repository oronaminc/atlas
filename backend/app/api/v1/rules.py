import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_editor
from app.core.envelope import envelope
from app.core.pagination import decode_cursor, page_meta
from app.db import get_db
from app.models import AlertRule, User
from app.models.rule import Datasource, ScopeType, Severity
from app.schemas.rule import (
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    EmergencyApplyRequest,
    RuleTestResult,
    RuleValidateResult,
)
from app.services.audit import record_audit, snapshot
from app.services.permissions import can_write_rule, can_write_rule_scope
from app.services.rule_sync import emergency_group_payload, mark_ruler_pending
from app.services.rule_validate import validate_expr

router = APIRouter(prefix="/rules", tags=["rules"])

RULE_AUDIT_FIELDS = [
    "name",
    "scope_type",
    "scope_ref_id",
    "expr",
    "for_duration",
    "severity",
    "enabled",
    "datasource",
]


def get_ruler_client():
    """Dependency so tests can inject a fake ruler."""
    from app.integrations.mimir_ruler import MimirRulerClient

    return MimirRulerClient()


def rule_out(rule: AlertRule) -> dict:
    return AlertRuleOut.model_validate(rule).model_dump(mode="json")


async def get_rule_or_404(db: AsyncSession, rule_id: uuid.UUID) -> AlertRule:
    rule = await db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.get("")
async def list_rules(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    q: str | None = None,
    scope_type: ScopeType | None = None,
    scope_ref_id: uuid.UUID | None = None,
    severity: Severity | None = None,
    enabled: bool | None = None,
    datasource: Datasource | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(AlertRule).order_by(AlertRule.created_at.desc(), AlertRule.id.desc())
    if q:
        stmt = stmt.where(AlertRule.name.ilike(f"%{q}%"))
    if scope_type is not None:
        stmt = stmt.where(AlertRule.scope_type == scope_type)
    if scope_ref_id is not None:
        stmt = stmt.where(AlertRule.scope_ref_id == scope_ref_id)
    if severity is not None:
        stmt = stmt.where(AlertRule.severity == severity)
    if enabled is not None:
        stmt = stmt.where(AlertRule.enabled == enabled)
    if datasource is not None:
        stmt = stmt.where(AlertRule.datasource == datasource)
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            t, i = decoded
            stmt = stmt.where(
                or_(
                    AlertRule.created_at < t,
                    (AlertRule.created_at == t) & (AlertRule.id < i),
                )
            )
    res = await db.execute(stmt.limit(limit + 1))
    items, meta = page_meta(list(res.scalars().unique()), limit)
    return envelope([rule_out(r) for r in items], meta=meta)


@router.post("", status_code=201)
async def create_rule(
    body: AlertRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    if not await can_write_rule_scope(db, user, body.scope_type, body.scope_ref_id):
        raise HTTPException(status_code=403, detail="No permission for this rule scope")
    rule = AlertRule(**body.model_dump(), created_by=user.id)
    db.add(rule)
    await db.flush()
    await record_audit(
        db,
        actor_id=user.id,
        action="create",
        resource_type="alert_rule",
        resource_id=rule.id,
        after=snapshot(rule, RULE_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await mark_ruler_pending(db)
    await db.commit()
    await db.refresh(rule)
    return envelope(rule_out(rule))


@router.get("/{rule_id}")
async def get_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return envelope(rule_out(await get_rule_or_404(db, rule_id)))


@router.patch("/{rule_id}")
async def update_rule(
    rule_id: uuid.UUID,
    body: AlertRuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rule = await get_rule_or_404(db, rule_id)
    if not await can_write_rule(db, user, rule):
        raise HTTPException(status_code=403, detail="No permission for this rule")
    before = snapshot(rule, RULE_AUDIT_FIELDS)
    update_data = body.model_dump(exclude_unset=True)
    new_scope_type = update_data.get("scope_type", rule.scope_type)
    new_scope_ref = update_data.get("scope_ref_id", rule.scope_ref_id)
    if not await can_write_rule_scope(db, user, new_scope_type, new_scope_ref):
        raise HTTPException(
            status_code=403, detail="No permission for the target scope"
        )
    for field, value in update_data.items():
        setattr(rule, field, value)
    rule.updated_by = user.id
    await record_audit(
        db,
        actor_id=user.id,
        action="update",
        resource_type="alert_rule",
        resource_id=rule.id,
        before=before,
        after=snapshot(rule, RULE_AUDIT_FIELDS),
        ip=client_ip(request),
    )
    await mark_ruler_pending(db)
    await db.commit()
    await db.refresh(rule)
    return envelope(rule_out(rule))


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rule = await get_rule_or_404(db, rule_id)
    if not await can_write_rule(db, user, rule):
        raise HTTPException(status_code=403, detail="No permission for this rule")
    before = snapshot(rule, RULE_AUDIT_FIELDS)
    await db.delete(rule)
    await record_audit(
        db,
        actor_id=user.id,
        action="delete",
        resource_type="alert_rule",
        resource_id=rule_id,
        before=before,
        ip=client_ip(request),
    )
    await mark_ruler_pending(db)
    await db.commit()
    return envelope({"ok": True})


@router.post("/{rule_id}/validate")
async def validate_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rule = await get_rule_or_404(db, rule_id)
    errors = await validate_expr(rule.expr, rule.datasource)
    return envelope(RuleValidateResult(valid=not errors, errors=errors).model_dump())


@router.post("/{rule_id}/enable")
async def enable_rule(
    rule_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _set_enabled(rule_id, True, request, db, user)


@router.post("/{rule_id}/disable")
async def disable_rule(
    rule_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _set_enabled(rule_id, False, request, db, user)


async def _set_enabled(
    rule_id: uuid.UUID, enabled: bool, request: Request, db: AsyncSession, user: User
):
    rule = await get_rule_or_404(db, rule_id)
    if not await can_write_rule(db, user, rule):
        raise HTTPException(status_code=403, detail="No permission for this rule")
    before = snapshot(rule, ["enabled"])
    rule.enabled = enabled
    rule.updated_by = user.id
    await record_audit(
        db,
        actor_id=user.id,
        action="enable" if enabled else "disable",
        resource_type="alert_rule",
        resource_id=rule.id,
        before=before,
        after={"enabled": enabled},
        ip=client_ip(request),
    )
    await mark_ruler_pending(db)
    await db.commit()
    await db.refresh(rule)
    return envelope(rule_out(rule))


@router.post("/{rule_id}/test")
async def test_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Evaluates the expression against current data (preview)."""
    rule = await get_rule_or_404(db, rule_id)
    try:
        if rule.datasource == Datasource.metrics:
            from app.integrations.mimir_ruler import MimirQueryClient

            client = MimirQueryClient()
        else:
            from app.integrations.loki import LokiClient

            client = LokiClient()
        try:
            data = await client.instant_query(rule.expr)
        finally:
            await client.aclose()
        result = data.get("data", {}).get("result", [])
        return envelope(RuleTestResult(success=True, result=result).model_dump())
    except Exception as exc:
        return envelope(RuleTestResult(success=False, error=str(exc)).model_dump())


@router.post("/emergency-apply")
async def emergency_apply(
    body: EmergencyApplyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
    ruler=Depends(get_ruler_client),
):
    """Emergency mode: validate, push the single rule to the Ruler immediately,
    and persist the change in the same transaction. Audited with emergency=true."""
    rule = await get_rule_or_404(db, body.rule_id)
    if not await can_write_rule(db, user, rule):
        raise HTTPException(status_code=403, detail="No permission for this rule")

    errors = await validate_expr(rule.expr, rule.datasource)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    namespace, payload = emergency_group_payload(rule)
    try:
        await ruler.set_rule_group(namespace, payload)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Ruler push failed: {exc}"
        ) from exc

    rule.enabled = True
    rule.updated_by = user.id
    await record_audit(
        db,
        actor_id=user.id,
        action="emergency_apply",
        resource_type="alert_rule",
        resource_id=rule.id,
        after={**snapshot(rule, RULE_AUDIT_FIELDS), "reason": body.reason},
        ip=client_ip(request),
        emergency=True,
    )
    await db.commit()
    await db.refresh(rule)
    return envelope({"rule": rule_out(rule), "namespace": namespace, "pushed": True})
