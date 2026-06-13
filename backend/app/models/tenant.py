"""Tenancy: subsidiaries identified by Mimir org (X-Scope-OrgID set by Alloy).

`tenants` is the registry; `mimir_org_map` maps N Mimir orgs -> 1 tenant.
Users carry users.tenant_id (NULL = HQ, sees everything).
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class Tenant(TimestampedBase):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # optional direct-push fallback (POST /ingest/{provider} without an org):
    # sha256 of a per-tenant ingest key; the Mimir-org path is primary.
    ingest_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class MimirOrgMap(TimestampedBase):
    """X-Scope-OrgID value -> tenant. N orgs may map to one tenant
    (a subsidiary running several Alloy fleets)."""

    __tablename__ = "mimir_org_map"

    mimir_org: Mapped[str] = mapped_column(String(200), unique=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
