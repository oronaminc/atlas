"""Active grouping rule resolution (IMP). v1 ships a single editable rule; the
schema holds many (priority-ordered) for later. Seeds the default lazily."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import NotificationDefault
from app.models.grouping import GroupingRule

DEFAULT_RULE = {
    "name": "service-l2",
    "label_keys": ["cmdb_service_l2_code"],
    "window_seconds": 900,
    "min_group_size": 2,
    "critical_immediate": True,
    "dedup_window_seconds": 300,
}


async def _top_rule(db: AsyncSession) -> GroupingRule | None:
    return (
        await db.execute(
            select(GroupingRule)
            .where(GroupingRule.enabled.is_(True))
            .order_by(GroupingRule.priority.desc(), GroupingRule.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_active_rule(db: AsyncSession) -> GroupingRule:
    """Highest-priority enabled rule; seeds the default if none exists.
    Race-safe: concurrent workers seeding on first run collide on the unique
    `name`; the loser rolls back the savepoint and re-reads the winner's row."""
    rule = await _top_rule(db)
    if rule is not None:
        return rule
    try:
        async with db.begin_nested():
            rule = GroupingRule(**DEFAULT_RULE)
            db.add(rule)
            await db.flush()
        return rule
    except IntegrityError:
        return await _top_rule(db)


async def get_notification_defaults(db: AsyncSession) -> NotificationDefault:
    """Single-row default channel toggles for new incidents; seeds if absent."""
    nd = (await db.execute(select(NotificationDefault).limit(1))).scalar_one_or_none()
    if nd is None:
        nd = NotificationDefault()
        db.add(nd)
        await db.flush()
    return nd
