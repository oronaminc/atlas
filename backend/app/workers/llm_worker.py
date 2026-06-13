"""LLM analysis worker (separate pod). Claims incident_analysis jobs
(CAS+lease) and runs them; slow/failing external LLM never blocks the
incident pipeline. Exposes /metrics+/healthz+/readyz on METRICS_PORT.
"""

import asyncio
import logging
import os
import time
import uuid

from sqlalchemy import func, select

from app.core import instruments
from app.core.config import settings
from app.db import async_session_factory
from app.models.base import utcnow
from app.models.llm import IncidentAnalysis
from app.services.llm_analysis import (
    claim_pending_analyses,
    enqueue_auto_analyses,
    run_analysis,
)
from app.workers.metrics_server import heartbeat, start_metrics_server

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
WORKER_ID = os.environ.get("HOSTNAME") or f"llm-{uuid.uuid4().hex[:8]}"


async def run_once() -> int:
    async with async_session_factory() as db:
        await enqueue_auto_analyses(db, now=utcnow())
        await db.commit()
        jobs = await claim_pending_analyses(db, worker_id=WORKER_ID, now=utcnow())
        for job in jobs:
            t0 = time.perf_counter()
            await run_analysis(db, job)
            instruments.llm_request_seconds.observe(time.perf_counter() - t0)
            instruments.llm_requests.inc(outcome=job.status)
            if job.tokens_used:
                instruments.llm_tokens.inc(job.tokens_used)
        await db.commit()
        pending = (
            await db.execute(
                select(func.count())
                .select_from(IncidentAnalysis)
                .where(IncidentAnalysis.status.in_(("pending", "failed")))
            )
        ).scalar_one()
        instruments.llm_analysis_pending.set(pending)
        return len(jobs)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await start_metrics_server("llm", port=settings.METRICS_PORT)
    logger.info("llm worker %s started", WORKER_ID)
    while True:
        try:
            n = await run_once()
            if n:
                logger.info("analysed %d incident(s)", n)
        except Exception:
            logger.exception("llm iteration failed")
        heartbeat("llm")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
