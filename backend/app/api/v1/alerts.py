"""Alert views proxied from the Mimir Alertmanager (read-only).

Tenancy: a tenant user reads their own org's Alertmanager; an HQ user
fans out across every active org concurrently (bounded), each alert
tagged with its tenant slug, optionally narrowed with ?tenant=<slug>.
Falls back to the default org when no org mappings exist (legacy)."""

import asyncio
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.notifications import get_alertmanager_client_for_org
from app.core.deps import apply_tenant_param, get_current_user
from app.core.envelope import envelope
from app.core.pagination import decode_cursor, page_meta
from app.core.tenancy import resolve_tenant_slug
from app.db import get_db
from app.models import User
from app.models.alerting import AlertEvent
from app.models.base import utcnow
from app.models.tenant import MimirOrgMap, Tenant
from app.schemas.alerting import AlertEventOut

router = APIRouter(prefix="/alerts", tags=["alerts"])

HQ_FANOUT_CONCURRENCY = 8

# label dimensions the browse/group-by API exposes (IMP §5), mapped to columns
_DENORM = {
    "cmdb_ci": AlertEvent.cmdb_ci,
    "cmdb_hostname": AlertEvent.cmdb_hostname,
    "cmdb_zone": AlertEvent.cmdb_zone,
    "client_address": AlertEvent.client_address,
    "cmdb_service_l1_code": AlertEvent.cmdb_service_l1_code,
    "cmdb_service_l2_code": AlertEvent.cmdb_service_l2_code,
}
_GROUP_BY = {"client_address", "cmdb_service_l1_code", "cmdb_service_l2_code"}


@router.get("")
async def list_alerts(
    cursor: str | None = None,
    limit: int = Query(default=50, le=200),
    cmdb_zone: str | None = None,
    cmdb_hostname: str | None = None,
    cmdb_ci: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    in_incident: bool | None = None,
    since_hours: int | None = Query(default=None, ge=1, le=720),
    group_by: str | None = Query(default=None, description="client_address|l1_code|l2_code"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(apply_tenant_param),
):
    """Browse EVERY stored alert (in an incident or not). Auto-scoped by the l2
    visibility choke point. `group_by` returns counts per dimension instead of a
    list. Filters are label-based (no server table)."""
    filters = []
    for col, val in (
        (AlertEvent.cmdb_zone, cmdb_zone),
        (AlertEvent.cmdb_hostname, cmdb_hostname),
        (AlertEvent.cmdb_ci, cmdb_ci),
        (AlertEvent.severity, severity),
        (AlertEvent.status, status),
    ):
        if val is not None:
            filters.append(col == val)
    if in_incident is not None:
        filters.append(
            AlertEvent.incident_id.isnot(None) if in_incident else AlertEvent.incident_id.is_(None)
        )
    if since_hours is not None:
        filters.append(AlertEvent.received_at >= utcnow() - timedelta(hours=since_hours))

    if group_by is not None:
        if group_by not in _GROUP_BY:
            raise HTTPException(status_code=422, detail=f"group_by must be one of {_GROUP_BY}")
        gcol = _DENORM[group_by]
        rows = (
            await db.execute(
                select(gcol.label("value"), func.count().label("count"))
                .where(*filters, gcol.isnot(None))
                .group_by(gcol)
                .order_by(func.count().desc())
            )
        ).all()
        return envelope([{"value": v, "count": c} for v, c in rows])

    stmt = (
        select(AlertEvent)
        .where(*filters)
        .order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
    )
    if cursor and (decoded := decode_cursor(cursor)):
        t, i = decoded
        stmt = stmt.where(
            or_(AlertEvent.created_at < t, (AlertEvent.created_at == t) & (AlertEvent.id < i))
        )
    res = await db.execute(stmt.limit(limit + 1))
    items, meta = page_meta(list(res.scalars().unique()), limit)
    return envelope(
        [AlertEventOut.model_validate(a).model_dump(mode="json") for a in items], meta=meta
    )


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


# defined LAST so the static /active and /history routes match before {alert_id}
@router.get("/{alert_id}")
async def get_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(apply_tenant_param),
):
    alert = (
        await db.execute(select(AlertEvent).where(AlertEvent.id == alert_id))
    ).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return envelope(AlertEventOut.model_validate(alert).model_dump(mode="json"))
