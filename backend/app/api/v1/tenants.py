"""Tenant management — HQ admin only (admin role + tenant_id NULL).

Tenants are subsidiaries; each maps 1..N Mimir orgs (the X-Scope-OrgID
values Alloy stamps). Listing slugs is open to any authenticated HQ user
for the dashboard tenant filter dropdown.
"""

import hashlib
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_hq_admin
from app.core.envelope import envelope
from app.core.tenancy import invalidate_org_cache
from app.db import get_db
from app.models import User
from app.models.tenant import MimirOrgMap, Tenant
from app.schemas.tenant import TenantCreate, TenantOut, TenantUpdate
from app.services.audit import record_audit

router = APIRouter(prefix="/tenants", tags=["tenants"])

TENANT_AUDIT_FIELDS = ["slug", "name", "is_active"]


async def _orgs_for(db: AsyncSession, tenant_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    rows = await db.execute(
        select(MimirOrgMap.tenant_id, MimirOrgMap.mimir_org).where(
            MimirOrgMap.tenant_id.in_(tenant_ids)
        )
    )
    out: dict[uuid.UUID, list[str]] = {}
    for tenant_id, org in rows.all():
        out.setdefault(tenant_id, []).append(org)
    return out


def _to_out(tenant: Tenant, orgs: list[str]) -> dict:
    return TenantOut(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        is_active=tenant.is_active,
        mimir_orgs=sorted(orgs),
        created_at=tenant.created_at,
    ).model_dump(mode="json")


@router.get("")
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """HQ users: full list (for the dashboard filter + admin UI).
    Tenant users: only their own tenant (for label display)."""
    stmt = select(Tenant).order_by(Tenant.slug)
    if user.tenant_id is not None:
        stmt = stmt.where(Tenant.id == user.tenant_id)
    tenants = list((await db.execute(stmt)).scalars())
    orgs = await _orgs_for(db, [t.id for t in tenants])
    return envelope([_to_out(t, orgs.get(t.id, [])) for t in tenants])


@router.post("", status_code=201)
async def create_tenant(
    body: TenantCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_hq_admin),
):
    dup = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Slug already exists")
    for org in body.mimir_orgs:
        taken = await db.execute(select(MimirOrgMap).where(MimirOrgMap.mimir_org == org))
        if taken.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Mimir org already mapped: {org}")

    ingest_key = secrets.token_urlsafe(32)
    tenant = Tenant(
        slug=body.slug,
        name=body.name,
        is_active=True,
        ingest_key_hash=hashlib.sha256(ingest_key.encode()).hexdigest(),
        created_by=admin.id,
    )
    db.add(tenant)
    await db.flush()
    for org in body.mimir_orgs:
        db.add(MimirOrgMap(mimir_org=org, tenant_id=tenant.id))
    await record_audit(
        db,
        actor_id=admin.id,
        action="create",
        resource_type="tenant",
        resource_id=tenant.id,
        after={"slug": tenant.slug, "name": tenant.name, "mimir_orgs": body.mimir_orgs},
        ip=client_ip(request),
    )
    await db.commit()
    invalidate_org_cache()
    out = _to_out(tenant, body.mimir_orgs)
    out["ingest_key"] = ingest_key  # shown exactly once
    return envelope(out)


@router.patch("/{tenant_id}")
async def update_tenant(
    tenant_id: uuid.UUID,
    body: TenantUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_hq_admin),
):
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    before = {f: getattr(tenant, f) for f in TENANT_AUDIT_FIELDS}
    if body.name is not None:
        tenant.name = body.name
    if body.is_active is not None:
        tenant.is_active = body.is_active
    if body.mimir_orgs is not None:
        existing = list(
            (
                await db.execute(select(MimirOrgMap).where(MimirOrgMap.tenant_id == tenant.id))
            ).scalars()
        )
        wanted = set(body.mimir_orgs)
        for row in existing:
            if row.mimir_org not in wanted:
                await db.delete(row)
        current = {row.mimir_org for row in existing}
        for org in wanted - current:
            taken = await db.execute(select(MimirOrgMap).where(MimirOrgMap.mimir_org == org))
            if taken.scalar_one_or_none():
                raise HTTPException(status_code=409, detail=f"Mimir org already mapped: {org}")
            db.add(MimirOrgMap(mimir_org=org, tenant_id=tenant.id))
    tenant.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="tenant",
        resource_id=tenant.id,
        before=before,
        after={f: getattr(tenant, f) for f in TENANT_AUDIT_FIELDS}
        | ({"mimir_orgs": body.mimir_orgs} if body.mimir_orgs is not None else {}),
        ip=client_ip(request),
    )
    await db.commit()
    invalidate_org_cache()
    orgs = await _orgs_for(db, [tenant.id])
    return envelope(_to_out(tenant, orgs.get(tenant.id, [])))
