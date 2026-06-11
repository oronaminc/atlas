"""DB-backed engine config (single row, seeded defaults, admin-editable)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import CorrelationConfig

DEFAULTS = {
    "dedup_window_seconds": 300,
    "correlation_window_seconds": 900,
    "group_attrs": ["host", "service", "cluster"],
}


async def get_config(db: AsyncSession) -> CorrelationConfig:
    res = await db.execute(select(CorrelationConfig).limit(1))
    config = res.scalar_one_or_none()
    if config is None:
        config = CorrelationConfig(**DEFAULTS)
        db.add(config)
        await db.flush()
    return config
