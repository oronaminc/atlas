"""Machine ingestion endpoint. Static-key auth (no JWT). Persists events
durably and acks 202; correlation happens asynchronously in the worker.

Tenancy: the PRIMARY path is org-qualified — each Mimir org's Alertmanager
config (provisioned by atlas) webhooks to /ingest/{provider}/{org}, and the
org (X-Scope-OrgID value stamped by Alloy upstream) resolves to a tenant via
mimir_org_map. The un-orged legacy route stays for one deprecation release
and for direct-push providers: there the tenant comes from a per-tenant
ingest key, falling back to the default (MIMIR_TENANT_ID) org's tenant.
"""

import hashlib
import logging
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.envelope import envelope
from app.core.tenancy import resolve_org_tenant
from app.db import get_db
from app.models.base import utcnow
from app.models.tenant import Tenant
from app.providers.registry import get_provider
from app.services.correlation.engine import build_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

ALERT_STREAM = "atlas:alerts:in"


def _presented_key(
    x_atlas_ingest_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> str | None:
    """Key from X-Atlas-Ingest-Key or Authorization: Bearer — Mimir
    Alertmanager webhooks can only set the latter (http_config)."""
    if x_atlas_ingest_key:
        return x_atlas_ingest_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return None


def _is_global_key(key: str) -> bool:
    expected = settings.INGEST_API_KEY
    return bool(expected) and secrets.compare_digest(key, expected)


async def _tenant_for_key(db: AsyncSession, key: str) -> uuid.UUID | None:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return (
        await db.execute(
            select(Tenant.id).where(Tenant.ingest_key_hash == digest, Tenant.is_active.is_(True))
        )
    ).scalar_one_or_none()


async def _enqueue(event_ids: list[str]) -> None:
    """Best-effort wake-up for the correlation worker; it also polls PG,
    so a missing Redis never loses alerts."""
    try:
        import redis.asyncio as aioredis

        redis = aioredis.from_url(settings.REDIS_URL)
        try:
            for event_id in event_ids:
                await redis.xadd(ALERT_STREAM, {"event_id": event_id})
        finally:
            await redis.aclose()
    except Exception:
        logger.debug("redis enqueue skipped; worker will pick events up via PG poll")


async def _ingest(
    db: AsyncSession,
    provider_name: str,
    payload: dict[str, Any],
    tenant_id: uuid.UUID | None,
) -> dict:
    try:
        provider = get_provider(provider_name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_name}") from e

    alerts = provider.parse(payload)
    now = utcnow()
    events = [build_event(alert, received_at=now, tenant_id=tenant_id) for alert in alerts]
    db.add_all(events)
    await db.commit()

    await _enqueue([str(e.id) for e in events])
    return envelope({"accepted": len(events)})


@router.post("/{provider_name}/{org}", status_code=202)
async def ingest_for_org(
    provider_name: str,
    org: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    key: str | None = Depends(_presented_key),
):
    """Primary tenant path: org = the X-Scope-OrgID this alert came from."""
    if key is None:
        raise HTTPException(status_code=401, detail="Missing ingest key")
    tenant_id = await resolve_org_tenant(db, org)
    if tenant_id is None:
        raise HTTPException(status_code=404, detail=f"Unknown or inactive org: {org}")
    if not _is_global_key(key) and await _tenant_for_key(db, key) != tenant_id:
        raise HTTPException(status_code=401, detail="Invalid ingest key")
    return await _ingest(db, provider_name, payload, tenant_id)


@router.post("/{provider_name}", status_code=202)
async def ingest(
    provider_name: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    key: str | None = Depends(_presented_key),
):
    """Legacy / direct-push path (deprecation window: one release).
    Tenant = per-tenant key owner, else the default org's tenant."""
    if key is None:
        raise HTTPException(status_code=401, detail="Missing ingest key")
    if _is_global_key(key):
        tenant_id = await resolve_org_tenant(db, settings.MIMIR_TENANT_ID)
    else:
        tenant_id = await _tenant_for_key(db, key)
        if tenant_id is None:
            raise HTTPException(status_code=401, detail="Invalid ingest key")
    return await _ingest(db, provider_name, payload, tenant_id)
