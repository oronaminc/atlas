"""Label discovery proxied from the Mimir label API (autocomplete + filter
choices). Whole-infra (not just alerted hosts), single default org, read-only.
On-demand (short request) — NOT cached in the DB like rules/silences.

Bounded to a recent window (admin-configured
mimir_query_config.label_query_lookback_hours, default 1h) when the caller omits
start/end: Mimir 422s an unbounded label query against a stale bucket index.
An explicit caller start/end is respected."""

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.db import get_db
from app.integrations.mimir_ruler import MimirQueryClient
from app.models import User
from app.services.mimir_sync import get_mimir_query_config

router = APIRouter(prefix="/labels", tags=["labels"])


def get_query_client() -> MimirQueryClient:
    """Injectable Mimir query client (default org); tests override this."""
    return MimirQueryClient()


async def _bounded(db: AsyncSession, start: str | None, end: str | None) -> tuple[str, str]:
    """Fill an omitted bound with the admin lookback window (unix seconds);
    respect whatever the caller explicitly passed."""
    cfg = await get_mimir_query_config(db)
    now = datetime.now(UTC)
    end = end or str(int(now.timestamp()))
    start = start or str(int((now - timedelta(hours=cfg.label_query_lookback_hours)).timestamp()))
    return start, end


def _raise_upstream(exc: Exception) -> None:
    """Surface the real Mimir status (e.g. 422 bucket-index-too-old) instead of a
    blanket 502; only connection-level failures become 502."""
    if isinstance(exc, httpx.HTTPStatusError):
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text[:500]
        ) from exc
    raise HTTPException(status_code=502, detail=f"Mimir unreachable: {exc}") from exc


@router.get("")
async def label_names(
    start: str | None = None,
    end: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    client: MimirQueryClient = Depends(get_query_client),
):
    start, end = await _bounded(db, start, end)
    try:
        names = await client.label_names(start=start, end=end)
    except Exception as exc:
        _raise_upstream(exc)
    finally:
        await client.aclose()
    return envelope(names)


@router.get("/{name}/values")
async def label_values(
    name: str,
    start: str | None = None,
    end: str | None = None,
    match: list[str] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    client: MimirQueryClient = Depends(get_query_client),
):
    start, end = await _bounded(db, start, end)
    try:
        values = await client.label_values(name, start=start, end=end, match=match)
    except Exception as exc:
        _raise_upstream(exc)
    finally:
        await client.aclose()
    return envelope(values)
