"""Machine ingestion endpoint. Static-key auth (no JWT). Persists events
durably and acks 202; correlation happens asynchronously in the worker.

Single default org (X-Scope-OrgID set by Alloy upstream); auth is the global
INGEST_API_KEY (X-Atlas-Ingest-Key or Authorization: Bearer — Mimir
Alertmanager webhooks can only set the latter via http_config)."""

import logging
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import instruments
from app.core.config import settings
from app.core.envelope import envelope
from app.db import get_db
from app.models.base import utcnow
from app.providers.registry import get_provider
from app.services.correlation.engine import build_event
from app.services.incident_service import resolve_incoming

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

ALERT_STREAM = "atlas:alerts:in"


def _presented_key(
    x_atlas_ingest_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> str | None:
    if x_atlas_ingest_key:
        return x_atlas_ingest_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return None


def _is_valid_key(key: str) -> bool:
    expected = settings.INGEST_API_KEY
    return bool(expected) and secrets.compare_digest(key, expected)


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
    key: str | None = Depends(_presented_key),
):
    if key is None:
        raise HTTPException(status_code=401, detail="Missing ingest key")
    if not _is_valid_key(key):
        raise HTTPException(status_code=401, detail="Invalid ingest key")

    start = time.perf_counter()
    try:
        provider = get_provider(provider_name)
    except KeyError as e:
        instruments.ingest_requests.inc(provider=provider_name, status="rejected")
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_name}") from e

    alerts = provider.parse(payload)
    now = utcnow()
    # batched webhook: each alerts[] element is handled INDIVIDUALLY. firing ->
    # stored + pushed through the pipeline; resolved -> state transition on the
    # matching stored alert (auto-resolve by the system), not a new row.
    firing = [a for a in alerts if a.status != "resolved"]
    resolved = [a for a in alerts if a.status == "resolved"]
    events = [build_event(alert, received_at=now) for alert in firing]
    db.add_all(events)
    await db.flush()
    for a in resolved:
        await resolve_incoming(db, a.source, a.name, a.labels or {}, now)
    await db.commit()

    await _enqueue([str(e.id) for e in events])
    accepted = len(firing) + len(resolved)
    instruments.ingest_requests.inc(provider=provider_name, status="accepted")
    instruments.ingest_events.inc(accepted, provider=provider_name)
    instruments.ingest_duration.observe(time.perf_counter() - start, provider=provider_name)
    return envelope({"accepted": accepted, "stored": len(events), "resolved": len(resolved)})
