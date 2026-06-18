"""Background sync worker.

Every SYNC_INTERVAL_SECONDS it serializes the rule groups to Prometheus YAML,
compares checksums, and PUTs only changed state to the Mimir Ruler
(X-Scope-OrgID injected by the integration client). A PG advisory lock makes
only one replica sync per tick when multiple workers run (correct for any N,
unlike the old Redis lock which failed open when Redis was down).
"""

import asyncio
import logging

from app.core.config import settings
from app.core.locks import advisory_lock
from app.db import async_session_factory
from app.integrations.alertmanager import AlertmanagerClient
from app.integrations.mimir_ruler import MimirRulerClient
from app.services.am_provision import provision_am_configs
from app.services.rule_sync import sync_all_rule_groups
from app.workers.metrics_server import heartbeat, start_metrics_server

logger = logging.getLogger(__name__)

SYNC_LOCK = "atlas:sync:ruler"


async def run_sync_once(ruler: MimirRulerClient) -> None:
    async with advisory_lock(SYNC_LOCK) as acquired:
        if not acquired:
            logger.debug("another worker holds the sync lock; skipping")
            return
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


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ruler = MimirRulerClient()
    await start_metrics_server("sync", port=settings.METRICS_PORT)
    logger.info("sync worker started (interval=%ss)", settings.SYNC_INTERVAL_SECONDS)
    while True:
        try:
            await run_sync_once(ruler)
        except Exception:
            logger.exception("sync iteration failed")
        heartbeat("sync")
        await asyncio.sleep(settings.SYNC_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
