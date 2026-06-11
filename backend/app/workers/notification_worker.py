"""Notification worker: fan-out (incident → outbox) + delivery (outbox →
channels). Separate pod so slow external APIs / retries never block alert
processing. Safe at replicas>1 (CAS+lease claims, at-least-once)."""

import asyncio
import logging
import os
import uuid

from app.db import async_session_factory
from app.models.base import utcnow
from app.notifications.channels.registry import build_channels
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending
from app.notifications.settings import get_notification_settings
from app.notifications.throttle import TokenBucket

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
WORKER_ID = os.environ.get("HOSTNAME") or f"notify-{uuid.uuid4().hex[:8]}"


async def run_once(throttle_cache: dict) -> tuple[int, int]:
    async with async_session_factory() as db:
        now = utcnow()
        created = await fan_out_pending(db, now=now)
        await db.commit()

        settings_row = await get_notification_settings(db)
        rate = settings_row.telegram_rate_per_second
        if throttle_cache.get("rate") != rate:
            throttle_cache["rate"] = rate
            throttle_cache["bucket"] = TokenBucket(rate_per_second=rate)

        channels = build_channels(settings_row)
        sent = await deliver_once(
            db,
            channels=channels,
            worker_id=WORKER_ID,
            now=utcnow(),
            throttle=throttle_cache["bucket"],
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
