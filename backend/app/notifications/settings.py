"""Single-row admin-managed notification settings, seeded defaults."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import NotificationSettings


async def get_notification_settings(db: AsyncSession) -> NotificationSettings:
    res = await db.execute(select(NotificationSettings).limit(1))
    row = res.scalar_one_or_none()
    if row is None:
        row = NotificationSettings(
            telegram_bot_token=None,
            telegram_rate_per_second=25,
            quota_group_per_hour=30,
            quota_global_per_day=500,
        )
        db.add(row)
        await db.flush()
    return row
