"""Machine ingestion endpoint. Static-key auth (no JWT). Persists events
durably and acks 202; correlation happens asynchronously in the worker."""

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.envelope import envelope
from app.db import get_db
from app.models.base import utcnow
from app.providers.registry import get_provider
from app.services.correlation.engine import build_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

ALERT_STREAM = "atlas:alerts:in"


def require_ingest_key(x_atlas_ingest_key: str | None = Header(default=None)) -> None:
    expected = settings.INGEST_API_KEY
    if not expected or not x_atlas_ingest_key:
        raise HTTPException(status_code=401, detail="Missing ingest key")
    if not secrets.compare_digest(x_atlas_ingest_key, expected):
        raise HTTPException(status_code=401, detail="Invalid ingest key")


async def _enqueue(event_ids: list[str]) -> None:
    """Best-effort wake-up for the correlation worker; it also polls PG,
    so a missing Redis never loses alerts."""
    try:
        import redis.asyncio as aioredis

        redis = aioredis.from_url(settings.REDIS_URL)
        try:
            for event_id in event_ids:
                await redis.xadd(ALERT_STREAM, {"event_id": event_id})
        finally:
            await redis.aclose()
    except Exception:
        logger.debug("redis enqueue skipped; worker will pick events up via PG poll")


@router.post("/{provider_name}", status_code=202)
async def ingest(
    provider_name: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_ingest_key),
):
    try:
        provider = get_provider(provider_name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_name}") from e

    alerts = provider.parse(payload)
    now = utcnow()
    events = [build_event(alert, received_at=now) for alert in alerts]
    db.add_all(events)
    await db.commit()

    await _enqueue([str(e.id) for e in events])
    return envelope({"accepted": len(events)})
