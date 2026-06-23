"""Mimir sync worker (separate pod): refreshes the rules + silences read-cache.

Pulls the Mimir rules API (config + eval state) and the Alertmanager silences
into atlas cache tables every MIMIR_SYNC_INTERVAL_SECONDS. A PG advisory lock
keeps one replica syncing at a time. Read-only pulls; no PromQL authoring.
"""

import asyncio
import logging

from app.core.config import settings
from app.core.locks import advisory_lock
from app.db import async_session_factory
from app.integrations.alertmanager import AlertmanagerClient
from app.integrations.mimir_ruler import MimirQueryClient
from app.services.mimir_sync import sync_rules, sync_silences
from app.workers.metrics_server import heartbeat, start_metrics_server

logger = logging.getLogger(__name__)

MIMIR_SYNC_LOCK = "atlas:mimir_sync"


async def run_once() -> None:
    async with advisory_lock(MIMIR_SYNC_LOCK) as acquired:
        if not acquired:
            logger.debug("another worker holds the mimir-sync lock; skipping")
            return
        query = MimirQueryClient()
        am = AlertmanagerClient()
        try:
            async with async_session_factory() as db:
                try:
                    n_rules = await sync_rules(db, query)
                except Exception:
                    logger.exception("rule sync failed")
                    n_rules = -1
                try:
                    n_silences = await sync_silences(db, am)
                except Exception:
                    logger.exception("silence sync failed")
                    n_silences = -1
                await db.commit()
            logger.info("mimir sync: %s rules, %s silences", n_rules, n_silences)
        finally:
            await query.aclose()
            await am.aclose()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await start_metrics_server("mimir_sync", port=settings.METRICS_PORT)
    logger.info("mimir-sync worker started (every %ss)", settings.MIMIR_SYNC_INTERVAL_SECONDS)
    while True:
        try:
            await run_once()
        except Exception:
            logger.exception("mimir-sync iteration failed")
        heartbeat("mimir_sync")
        await asyncio.sleep(settings.MIMIR_SYNC_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
