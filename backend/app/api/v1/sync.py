from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.db import get_db
from app.models import SyncState, User
from app.schemas.sync import SyncStateOut

router = APIRouter(tags=["sync"])


@router.get("/sync-state")
async def sync_state(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    res = await db.execute(select(SyncState))
    return envelope([SyncStateOut.model_validate(s).model_dump(mode="json") for s in res.scalars()])
