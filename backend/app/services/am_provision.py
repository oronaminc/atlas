"""Provision each Mimir org's Alertmanager config to webhook back into atlas.

Atlas owns the org-qualified webhook URL (/api/v1/ingest/alertmanager/{org})
— the org in the URL is written by US into that org's AM config, so the
tenant attribution on the ingest path is provisioned, not caller-claimed.
AM can only set an Authorization header (http_config), hence the ingest
endpoint also accepts the key as a Bearer token.

Enabled via AM_PROVISION_ENABLED + ATLAS_PUBLIC_URL; the sync worker pushes
once per cycle.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.tenant import MimirOrgMap, Tenant

logger = logging.getLogger(__name__)


def build_am_config(org: str) -> dict[str, Any]:
    return {
        "route": {"receiver": "atlas"},
        "receivers": [
            {
                "name": "atlas",
                "webhook_configs": [
                    {
                        "url": f"{settings.ATLAS_PUBLIC_URL}/api/v1/ingest/alertmanager/{org}",
                        "send_resolved": True,
                        "http_config": {
                            "authorization": {
                                "type": "Bearer",
                                "credentials": settings.INGEST_API_KEY,
                            }
                        },
                    }
                ],
            }
        ],
    }


async def active_orgs(db: AsyncSession) -> list[str]:
    rows = await db.execute(
        select(MimirOrgMap.mimir_org)
        .join(Tenant, Tenant.id == MimirOrgMap.tenant_id)
        .where(Tenant.is_active.is_(True))
        .order_by(MimirOrgMap.mimir_org)
    )
    return list(rows.scalars())


async def provision_am_configs(db: AsyncSession, am_factory) -> int:
    """Push the atlas webhook config into every active org's Alertmanager.
    `am_factory(org)` -> AlertmanagerClient. Returns orgs provisioned."""
    if not settings.AM_PROVISION_ENABLED or not settings.ATLAS_PUBLIC_URL:
        return 0
    count = 0
    for org in await active_orgs(db):
        try:
            await am_factory(org).set_config(build_am_config(org))
            count += 1
        except Exception:
            logger.exception("AM provisioning failed for org %s", org)
    return count
