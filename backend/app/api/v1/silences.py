"""Silences. READ from the atlas cache (mimir_silences, synced from the Mimir
Alertmanager) — open to all authenticated users. WRITE (create/expire) goes
straight to the Alertmanager (editor+); atlas builds the label matcher from the
chosen service (cmdb_service_l2_code) or server (cmdb_ci) — the user never writes
a query/matcher. A silence (Mimir-side) blocks the alert entirely; it coexists
with the atlas-side per-incident notification toggle."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.notifications import get_alertmanager_client
from app.core.deps import client_ip, get_current_user, require_editor
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.mimir import MimirSilence
from app.schemas.rule import SilenceCreate, SilenceOut
from app.services.audit import record_audit
from app.services.mimir_sync import sync_silences

router = APIRouter(prefix="/silences", tags=["silences"])

# the user's "what to silence" choice -> the AM matcher label (A6)
_MATCHER_LABEL = {"service": "cmdb_service_l2_code", "server": "cmdb_ci"}


@router.get("")
async def list_silences(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = (await db.execute(select(MimirSilence).order_by(MimirSilence.ends_at.desc()))).scalars()
    return envelope([SilenceOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("", status_code=201)
async def create_silence(
    body: SilenceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
    am=Depends(get_alertmanager_client),
):
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be after starts_at")
    matcher = {
        "name": _MATCHER_LABEL[body.target_kind],
        "value": body.target_value,
        "isRegex": False,
        "isEqual": True,
    }
    payload = {
        "matchers": [matcher],
        "startsAt": body.starts_at.isoformat(),
        "endsAt": body.ends_at.isoformat(),
        "comment": body.comment,
        "createdBy": user.username,
    }
    try:
        silence_id = await am.create_silence(payload)
        await sync_silences(db, am)  # reflect it in the read cache immediately
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Alertmanager unreachable: {exc}") from exc
    finally:
        await am.aclose()
    await record_audit(
        db,
        actor_id=user.id,
        action="create",
        resource_type="silence",
        resource_id=None,
        after={"silence_id": silence_id, "matcher": matcher, "comment": body.comment},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"silence_id": silence_id, "matcher": matcher})


@router.delete("/{silence_id}")
async def delete_silence(
    silence_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
    am=Depends(get_alertmanager_client),
):
    try:
        await am.delete_silence(silence_id)
        await sync_silences(db, am)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Alertmanager unreachable: {exc}") from exc
    finally:
        await am.aclose()
    await record_audit(
        db,
        actor_id=user.id,
        action="delete",
        resource_type="silence",
        resource_id=None,
        before={"silence_id": silence_id},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})
