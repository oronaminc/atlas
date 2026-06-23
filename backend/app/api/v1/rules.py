"""Read-only view of Mimir Ruler rules from the atlas read-cache (mimir_rules).

The mimir_sync worker keeps the cache fresh; this endpoint never hits Mimir on
the request path. atlas authors no PromQL — the operator only SELECTs a pulled
rule (e.g. to attach a threshold override). Rule eval-state + last_error are
surfaced so a rule failing in Mimir is visible here."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.mimir import MimirRule
from app.schemas.rule import PulledRuleOut

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("/pulled")
async def pulled_rules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """All cached alerting rules (synced from Mimir), one entry per alert."""
    rows = (await db.execute(select(MimirRule).order_by(MimirRule.alertname))).scalars()
    return envelope([PulledRuleOut.model_validate(r).model_dump(mode="json") for r in rows])
