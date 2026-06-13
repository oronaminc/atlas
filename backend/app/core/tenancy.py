"""Tenancy choke point. THE single enforcement site for row-level isolation.

How it works:
- `get_current_user` (core/deps.py) calls `set_tenant_scope(db, user.tenant_id)`
  on every authenticated request. HQ users (tenant_id NULL) set scope None.
- A global `do_orm_execute` listener adds `with_loader_criteria(TenantScoped,
  tenant_id == scope)` to EVERY ORM SELECT in a scoped session — endpoints
  never write tenant filters, so none can forget one. NULL-tenant (legacy/
  system) rows are visible only to HQ.
- A `before_flush` listener stamps tenant_id on new TenantScoped rows when a
  scope is set, so a tenant user can never create a row outside their tenant.
- Workers/ingest run unscoped sessions (cross-tenant by design) and stamp
  tenant_id explicitly per row from the event/incident they process.

Org resolution: Alloy stamps X-Scope-OrgID per subsidiary; mimir_org_map
turns that org into a tenant_id (N orgs -> 1 tenant), cached briefly because
it sits on the ingest hot path (~225 rps/worker budget, Phase 1).
"""

import time
import uuid

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.base import TenantScoped
from app.models.tenant import MimirOrgMap, Tenant

_SCOPE_KEY = "tenant_scope"

# org -> (tenant_id | None, expiry); None caches "unknown org" briefly too
_ORG_CACHE: dict[str, tuple[uuid.UUID | None, float]] = {}
_ORG_CACHE_TTL = 30.0


def set_tenant_scope(db: AsyncSession, tenant_id: uuid.UUID | None) -> None:
    db.sync_session.info[_SCOPE_KEY] = tenant_id


def get_tenant_scope(db: AsyncSession) -> uuid.UUID | None:
    return db.sync_session.info.get(_SCOPE_KEY)


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_criteria(execute_state) -> None:
    if not execute_state.is_select or execute_state.is_column_load:
        return
    scope = execute_state.session.info.get(_SCOPE_KEY)
    if scope is None:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda cls: cls.tenant_id == scope,
            include_aliases=True,
            track_closure_variables=False,
        )
    )


@event.listens_for(Session, "before_flush")
def _stamp_tenant_on_new_rows(session, _flush_context, _instances) -> None:
    scope = session.info.get(_SCOPE_KEY)
    if scope is None:
        return
    for obj in session.new:
        if isinstance(obj, TenantScoped) and obj.tenant_id is None:
            obj.tenant_id = scope


async def resolve_org_tenant(db: AsyncSession, mimir_org: str) -> uuid.UUID | None:
    """X-Scope-OrgID value -> tenant_id (only active tenants). Cached."""
    now = time.monotonic()
    hit = _ORG_CACHE.get(mimir_org)
    if hit is not None and hit[1] > now:
        return hit[0]
    row = (
        await db.execute(
            select(MimirOrgMap.tenant_id)
            .join(Tenant, Tenant.id == MimirOrgMap.tenant_id)
            .where(MimirOrgMap.mimir_org == mimir_org, Tenant.is_active.is_(True))
        )
    ).scalar_one_or_none()
    _ORG_CACHE[mimir_org] = (row, now + _ORG_CACHE_TTL)
    return row


def invalidate_org_cache() -> None:
    _ORG_CACHE.clear()


async def resolve_tenant_slug(db: AsyncSession, slug: str) -> Tenant | None:
    return (
        await db.execute(select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True)))
    ).scalar_one_or_none()
