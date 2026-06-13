"""Background sync worker.

Every SYNC_INTERVAL_SECONDS it serializes the rule groups to Prometheus YAML,
compares checksums, and PUTs only changed state to the Mimir Ruler
(X-Scope-OrgID injected by the integration client). A Redis lock prevents
concurrent syncs when multiple workers run.
"""

import asyncio
import logging

import redis.asyncio as aioredis

from app.core import instruments
from app.core.config import settings
from app.db import async_session_factory
from app.integrations.alertmanager import AlertmanagerClient
from app.integrations.mimir_ruler import MimirRulerClient
from app.services.am_provision import provision_am_configs
from app.services.rule_sync import sync_all_rule_groups
from app.workers.metrics_server import heartbeat, start_metrics_server

logger = logging.getLogger(__name__)

LOCK_KEY = "atlas:sync:ruler:lock"
LOCK_TTL_SECONDS = 60


async def run_sync_once(ruler: MimirRulerClient, redis: aioredis.Redis | None) -> None:
    if redis is not None:
        acquired = await redis.set(LOCK_KEY, "1", nx=True, ex=LOCK_TTL_SECONDS)
        if not acquired:
            logger.debug("another worker holds the sync lock; skipping")
            return
    try:
        async with async_session_factory() as db:
            state = await sync_all_rule_groups(
                db, ruler, ruler_factory=lambda org: MimirRulerClient(org=org)
            )
            provisioned = await provision_am_configs(
                db, am_factory=lambda org: AlertmanagerClient(org=org)
            )
            await db.commit()
            logger.info(
                "ruler sync: status=%s, am orgs provisioned=%d", state.status.value, provisioned
            )
    finally:
        if redis is not None:
            try:
                await redis.delete(LOCK_KEY)
            except Exception:
                pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ruler = MimirRulerClient()
    try:
        redis: aioredis.Redis | None = aioredis.from_url(settings.REDIS_URL)
        await redis.ping()
    except Exception:
        logger.warning("redis unavailable; running without the distributed sync lock")
        redis = None

    await start_metrics_server("sync", port=settings.METRICS_PORT)
    instruments.redis_up.set(1 if redis is not None else 0)
    logger.info("sync worker started (interval=%ss)", settings.SYNC_INTERVAL_SECONDS)
    while True:
        try:
            await run_sync_once(ruler, redis)
        except Exception:
            logger.exception("sync iteration failed")
        heartbeat("sync")
        await asyncio.sleep(settings.SYNC_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
