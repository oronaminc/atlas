"""Silences read from the atlas cache (mimir_silences), synced from the Mimir
Alertmanager. View is open to all authenticated users; WRITE (create/expire)
lands in a later stage (editor+, calls Alertmanager directly)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.mimir import MimirSilence
from app.schemas.rule import SilenceOut

router = APIRouter(prefix="/silences", tags=["silences"])


@router.get("")
async def list_silences(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = (await db.execute(select(MimirSilence).order_by(MimirSilence.ends_at.desc()))).scalars()
    return envelope([SilenceOut.model_validate(r).model_dump(mode="json") for r in rows])
