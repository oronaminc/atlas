"""Alert views proxied from the Mimir Alertmanager (read-only).

Tenancy: a tenant user reads their own org's Alertmanager; an HQ user
fans out across every active org concurrently (bounded), each alert
tagged with its tenant slug, optionally narrowed with ?tenant=<slug>.
Falls back to the default org when no org mappings exist (legacy)."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.notifications import get_alertmanager_client_for_org
from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.core.tenancy import resolve_tenant_slug
from app.db import get_db
from app.models import User
from app.models.tenant import MimirOrgMap, Tenant

router = APIRouter(prefix="/alerts", tags=["alerts"])

HQ_FANOUT_CONCURRENCY = 8


def get_am_factory():
    """Injectable AM client factory (org -> client); tests override this."""
    return get_alertmanager_client_for_org


async def _org_slug_pairs(
    db: AsyncSession, user: User, tenant: str | None
) -> list[tuple[str | None, str | None]]:
    """(mimir_org, tenant_slug) pairs the caller may read."""
    stmt = (
        select(MimirOrgMap.mimir_org, Tenant.slug)
        .join(Tenant, Tenant.id == MimirOrgMap.tenant_id)
        .where(Tenant.is_active.is_(True))
        .order_by(MimirOrgMap.mimir_org)
    )
    if user.tenant_id is not None:
        stmt = stmt.where(Tenant.id == user.tenant_id)
    elif tenant:
        target = await resolve_tenant_slug(db, tenant)
        if target is None:
            raise HTTPException(status_code=404, detail="Unknown tenant")
        stmt = stmt.where(Tenant.id == target.id)
    pairs = [(org, slug) for org, slug in (await db.execute(stmt)).all()]
    if not pairs and user.tenant_id is None and not tenant:
        pairs = [(None, None)]  # legacy: default org, untagged
    return pairs


async def _fetch_alerts(db: AsyncSession, user: User, tenant: str | None, am_factory) -> list[dict]:
    pairs = await _org_slug_pairs(db, user, tenant)
    sem = asyncio.Semaphore(HQ_FANOUT_CONCURRENCY)

    async def fetch(org: str | None, slug: str | None) -> list[dict]:
        async with sem:
            am = am_factory(org)
            alerts = await am.get_active_alerts()
        if slug:
            for alert in alerts:
                alert["tenant"] = slug
        return alerts

    results = await asyncio.gather(*(fetch(org, slug) for org, slug in pairs))
    return [a for chunk in results for a in chunk]


@router.get("/active")
async def active_alerts(
    tenant: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    am_factory=Depends(get_am_factory),
):
    try:
        alerts = await _fetch_alerts(db, user, tenant, am_factory)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Alertmanager unreachable: {exc}") from exc
    return envelope(alerts)


@router.get("/history")
async def alert_history(
    tenant: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    am_factory=Depends(get_am_factory),
):
    """Alertmanager keeps no long-term history; resolved/silenced alerts that
    are still in its memory are returned. TODO: back with Loki ruler-evaluation
    logs or a recording pipeline if longer retention is needed."""
    try:
        alerts = await _fetch_alerts(db, user, tenant, am_factory)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Alertmanager unreachable: {exc}") from exc
    return envelope(alerts)
