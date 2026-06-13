"""LLM endpoint config admin (per-service, mirrors notification-settings).
api_key Fernet-encrypted + MASKED in responses. Tenant-admin edits its own
service; HQ picks via ?tenant=<slug>. Audited."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, require_admin
from app.core.envelope import envelope
from app.core.security import encrypt_secret
from app.core.tenancy import resolve_tenant_slug
from app.db import get_db
from app.models import User
from app.models.llm import LLMConfig
from app.schemas.llm import MASKED, LLMConfigOut, LLMConfigUpdate
from app.services.audit import record_audit

router = APIRouter(prefix="/llm-config", tags=["llm"])

AUDIT_FIELDS = [
    "enabled",
    "base_url",
    "model",
    "max_prompt_chars",
    "max_completion_tokens",
    "daily_quota",
    "auto_analyze",
    "redact_external_strict",
]


async def _config_tenant_id(
    tenant: str | None = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> uuid.UUID | None:
    if admin.tenant_id is not None:
        return admin.tenant_id
    if tenant:
        target = await resolve_tenant_slug(db, tenant)
        if target is None:
            raise HTTPException(status_code=404, detail="Unknown tenant")
        return target.id
    return None


async def _get_or_create(db: AsyncSession, tenant_id: uuid.UUID | None) -> LLMConfig:
    row = (
        await db.execute(select(LLMConfig).where(LLMConfig.tenant_id == tenant_id).limit(1))
    ).scalar_one_or_none()
    if row is None:
        row = LLMConfig(tenant_id=tenant_id)
        db.add(row)
        await db.flush()
    return row


def _out(row: LLMConfig) -> dict:
    return LLMConfigOut(
        enabled=row.enabled,
        base_url=row.base_url,
        api_key=MASKED if row.api_key else None,
        model=row.model,
        max_prompt_chars=row.max_prompt_chars,
        max_completion_tokens=row.max_completion_tokens,
        daily_quota=row.daily_quota,
        auto_analyze=row.auto_analyze,
        redact_external_strict=row.redact_external_strict,
    ).model_dump(mode="json")


def _snapshot(row: LLMConfig) -> dict:
    snap = {f: getattr(row, f) for f in AUDIT_FIELDS}
    snap["api_key_set"] = bool(row.api_key)
    return snap


@router.get("")
async def read_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
    tenant_id: uuid.UUID | None = Depends(_config_tenant_id),
):
    row = await _get_or_create(db, tenant_id)
    await db.commit()
    return envelope(_out(row))


@router.patch("")
async def update_config(
    body: LLMConfigUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
    tenant_id: uuid.UUID | None = Depends(_config_tenant_id),
):
    row = await _get_or_create(db, tenant_id)
    before = _snapshot(row)
    data = body.model_dump(exclude_unset=True)
    key = data.pop("api_key", MASKED)
    if key != MASKED:
        row.api_key = encrypt_secret(key) if key else None
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="llm_config",
        resource_id=row.id,
        before=before,
        after=_snapshot(row),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(row)
    return envelope(_out(row))
