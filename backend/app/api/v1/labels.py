"""Label discovery proxied from the Mimir label API (autocomplete + filter
choices). Whole-infra (not just alerted hosts), single default org, read-only.
On-demand (short request) — NOT cached in the DB like rules/silences."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.integrations.mimir_ruler import MimirQueryClient
from app.models import User

router = APIRouter(prefix="/labels", tags=["labels"])


def get_query_client() -> MimirQueryClient:
    """Injectable Mimir query client (default org); tests override this."""
    return MimirQueryClient()


@router.get("")
async def label_names(
    start: str | None = None,
    end: str | None = None,
    _: User = Depends(get_current_user),
    client: MimirQueryClient = Depends(get_query_client),
):
    try:
        names = await client.label_names(start=start, end=end)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mimir unreachable: {exc}") from exc
    finally:
        await client.aclose()
    return envelope(names)


@router.get("/{name}/values")
async def label_values(
    name: str,
    start: str | None = None,
    end: str | None = None,
    match: list[str] | None = Query(default=None),
    _: User = Depends(get_current_user),
    client: MimirQueryClient = Depends(get_query_client),
):
    try:
        values = await client.label_values(name, start=start, end=end, match=match)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mimir unreachable: {exc}") from exc
    finally:
        await client.aclose()
    return envelope(values)
