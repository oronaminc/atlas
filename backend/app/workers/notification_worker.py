"""Notification worker: fan-out (incident → outbox) + delivery (outbox →
channels). Separate pod so slow external APIs / retries never block alert
processing. Safe at replicas>1 (CAS+lease claims, at-least-once)."""

import asyncio
import logging
import os
import uuid

from app.db import async_session_factory
from app.models.base import utcnow
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
WORKER_ID = os.environ.get("HOSTNAME") or f"notify-{uuid.uuid4().hex[:8]}"


async def run_once(throttles: dict) -> tuple[int, int]:
    async with async_session_factory() as db:
        now = utcnow()
        created = await fan_out_pending(db, now=now)
        await db.commit()

        # settings/channels/throttle resolve PER TENANT inside deliver_once;
        # `throttles` (tenant_id -> TokenBucket) persists across passes.
        sent = await deliver_once(
            db,
            worker_id=WORKER_ID,
            now=utcnow(),
            throttles=throttles,
        )
        await db.commit()
        return created, sent


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("notification worker %s started", WORKER_ID)
    throttle_cache: dict = {}
    while True:
        try:
            created, sent = await run_once(throttle_cache)
            if created or sent:
                logger.info("fanned out %d, delivered %d", created, sent)
        except Exception:
            logger.exception("notification iteration failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
