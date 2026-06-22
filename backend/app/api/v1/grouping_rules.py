"""Admin CRUD for the topology grouping criteria (IMP §2). v1 ships a single
editable rule (group by cmdb_service_l2_code); the schema holds many for later."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_admin
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.grouping import GroupingRule
from app.services.audit import record_audit
from app.services.grouping_config import get_active_rule

router = APIRouter(prefix="/grouping-rules", tags=["grouping-rules"])


class GroupingRuleOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    enabled: bool
    priority: int
    label_keys: list[str]
    window_seconds: int
    min_group_size: int
    critical_immediate: bool
    dedup_window_seconds: int


class GroupingRuleUpdate(BaseModel):
    enabled: bool | None = None
    label_keys: list[str] | None = None
    window_seconds: int | None = None
    min_group_size: int | None = None
    critical_immediate: bool | None = None
    dedup_window_seconds: int | None = None


@router.get("")
async def list_rules(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    await get_active_rule(db)  # seed the default if empty
    await db.commit()
    rows = (await db.execute(select(GroupingRule).order_by(GroupingRule.priority.desc()))).scalars()
    return envelope([GroupingRuleOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.patch("/{rule_id}")
async def update_rule(
    rule_id: uuid.UUID,
    body: GroupingRuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    rule = await db.get(GroupingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Grouping rule not found")
    data = body.model_dump(exclude_unset=True)
    if "label_keys" in data and not data["label_keys"]:
        raise HTTPException(status_code=422, detail="label_keys cannot be empty")
    for k, v in data.items():
        setattr(rule, k, v)
    await record_audit(
        db,
        actor_id=user.id,
        action="update",
        resource_type="grouping_rule",
        resource_id=rule.id,
        after=data,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(rule)
    return envelope(GroupingRuleOut.model_validate(rule).model_dump(mode="json"))
