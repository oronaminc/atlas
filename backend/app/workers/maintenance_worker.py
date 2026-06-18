"""Maintenance worker (separate pod): partitions ahead, DEFAULT re-homing,
retention drops/deletes (+ optional archive), hourly rollups.

Runs a full pass on start, then every MAINTENANCE_INTERVAL_SECONDS (6h).
Rollups alone refresh every ROLLUP_INTERVAL_SECONDS (15min) so /stats stays
fresh; the stats endpoints additionally live-scan everything after the last
rolled-up hour, so worker downtime degrades latency, never correctness.
A PG advisory lock prevents concurrent passes across replicas (any N; correct
even when Redis is down, unlike the old Redis lock).
"""

import asyncio
import logging
import time

from app.core import instruments
from app.core.config import settings
from app.core.locks import advisory_lock
from app.db import async_session_factory
from app.services.maintenance import rollup_hourly, run_maintenance
from app.workers.metrics_server import heartbeat, start_metrics_server

logger = logging.getLogger(__name__)

MAINTENANCE_LOCK = "atlas:maintenance"
MAINTENANCE_INTERVAL_SECONDS = 6 * 3600
ROLLUP_INTERVAL_SECONDS = 15 * 60


async def run_once(*, full: bool) -> None:
    async with advisory_lock(MAINTENANCE_LOCK) as acquired:
        if not acquired:
            logger.debug("another worker holds the maintenance lock; skipping")
            return
        async with async_session_factory() as db:
            if full:
                summary = await run_maintenance(db)
                await db.commit()
                instruments.retention_partitions_dropped.inc(len(summary["partitions_dropped"]))
                instruments.maintenance_last_run.set(time.time())
                logger.info("maintenance pass: %s", summary)
                if summary["default_partition_rows"]:
                    logger.warning(
                        "DEFAULT partition holds %d rows after re-homing",
                        summary["default_partition_rows"],
                    )
            else:
                n = await rollup_hourly(db)
                await db.commit()
                logger.info("rollup refresh: %d buckets", n)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await start_metrics_server("maintenance", port=settings.METRICS_PORT)
    logger.info("maintenance worker started (full=%ss)", MAINTENANCE_INTERVAL_SECONDS)
    elapsed_since_full = MAINTENANCE_INTERVAL_SECONDS  # full pass on start
    while True:
        full = elapsed_since_full >= MAINTENANCE_INTERVAL_SECONDS
        try:
            await run_once(full=full)
        except Exception:
            logger.exception("maintenance iteration failed")
        if full:
            elapsed_since_full = 0
        heartbeat("maintenance")
        await asyncio.sleep(ROLLUP_INTERVAL_SECONDS)
        elapsed_since_full += ROLLUP_INTERVAL_SECONDS


if __name__ == "__main__":
    asyncio.run(main())
