"""Per-tenant notification settings (bot token, rate, quotas).

One row per tenant; tenant_id NULL = the legacy/platform-default row used
for un-attributed (NULL-tenant) notifications. Tenant A's token/quotas are
never consulted for tenant B's sends — deliver_once resolves settings by
the notification row's tenant_id.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import NotificationSettings


async def get_notification_settings(
    db: AsyncSession, tenant_id: uuid.UUID | None = None
) -> NotificationSettings:
    res = await db.execute(
        select(NotificationSettings).where(NotificationSettings.tenant_id == tenant_id).limit(1)
    )
    row = res.scalar_one_or_none()
    if row is None:
        row = NotificationSettings(
            tenant_id=tenant_id,
            telegram_bot_token=None,
            telegram_rate_per_second=25,
            quota_group_per_hour=30,
            quota_global_per_day=500,
        )
        db.add(row)
        await db.flush()
    return row
