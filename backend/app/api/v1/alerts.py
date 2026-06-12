"""Alert views proxied from the Mimir Alertmanager (read-only)."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.notifications import get_alertmanager_client
from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.models import User

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/active")
async def active_alerts(
    _: User = Depends(get_current_user),
    am=Depends(get_alertmanager_client),
):
    try:
        alerts = await am.get_active_alerts()
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Alertmanager unreachable: {exc}"
        ) from exc
    return envelope(alerts)


@router.get("/history")
async def alert_history(
    _: User = Depends(get_current_user),
    am=Depends(get_alertmanager_client),
):
    """Alertmanager keeps no long-term history; resolved/silenced alerts that
    are still in its memory are returned. TODO: back with Loki ruler-evaluation
    logs or a recording pipeline if longer retention is needed."""
    try:
        alerts = await am.get_active_alerts()
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Alertmanager unreachable: {exc}"
        ) from exc
    return envelope(alerts)
