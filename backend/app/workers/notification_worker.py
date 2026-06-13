"""Notification worker: fan-out (incident → outbox) + delivery (outbox →
channels). Separate pod so slow external APIs / retries never block alert
processing. Safe at replicas>1 (CAS+lease claims, at-least-once)."""

import asyncio
import logging
import os
import uuid

from app.core.config import settings
from app.db import async_session_factory
from app.models.base import utcnow
from app.notifications.delivery import deliver_once
from app.notifications.fanout import FANOUT_BATCH, fan_out_pending
from app.workers.metrics_server import heartbeat, start_metrics_server

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
WORKER_ID = os.environ.get("HOSTNAME") or f"notify-{uuid.uuid4().hex[:8]}"


async def run_once(throttles: dict) -> tuple[int, int, bool]:
    """Returns (created, sent, more_pending). more_pending=True means a full
    fan-out or delivery batch was processed, so the caller should loop again
    immediately instead of sleeping (drains storms at the rate budget, not at
    1 batch / poll-interval)."""
    async with async_session_factory() as db:
        now = utcnow()
        created = await fan_out_pending(db, now=now)
        await db.commit()

        # settings/channels/throttle resolve PER TENANT inside deliver_once;
        # `throttles` (tenant_id -> TokenBucket) persists across passes.
        result = await deliver_once(
            db,
            worker_id=WORKER_ID,
            now=utcnow(),
            throttles=throttles,
        )
        await db.commit()
        more_pending = created >= FANOUT_BATCH or result.was_full
        return created, int(result), more_pending


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await start_metrics_server("notification", port=settings.METRICS_PORT)
    logger.info("notification worker %s started", WORKER_ID)
    throttle_cache: dict = {}
    while True:
        try:
            created, sent, more_pending = await run_once(throttle_cache)
            if created or sent:
                logger.info("fanned out %d, delivered %d", created, sent)
            if more_pending:
                continue  # busy: re-loop immediately, skip the idle sleep
        except Exception:
            logger.exception("notification iteration failed")
        heartbeat("notification")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
