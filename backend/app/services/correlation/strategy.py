"""Stage-2 correlation strategies (pluggable)."""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import Incident, IncidentStatus
from app.schemas.alerting import NormalizedAlert

logger = logging.getLogger(__name__)


class CorrelationStrategy(Protocol):
    async def find_incident(
        self,
        db: AsyncSession,
        alert: NormalizedAlert,
        group_key: str | None,
        *,
        now: datetime,
        window_seconds: int,
        tenant_id: uuid.UUID | None = None,
    ) -> Incident | None: ...


class AttributeTimeStrategy:
    """Rule-based: open incident sharing the group key, seen within the window.
    Resolved incidents are never re-opened (new incident instead)."""

    async def find_incident(
        self,
        db: AsyncSession,
        alert: NormalizedAlert,
        group_key: str | None,
        *,
        now: datetime,
        window_seconds: int,
        tenant_id: uuid.UUID | None = None,
    ) -> Incident | None:
        if group_key is None:
            return None
        cutoff = now - timedelta(seconds=window_seconds)
        res = await db.execute(
            select(Incident)
            .where(
                Incident.group_key == group_key,
                Incident.tenant_id == tenant_id,
                Incident.status != IncidentStatus.resolved,
                Incident.last_seen >= cutoff,
            )
            .order_by(Incident.last_seen.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()


class LLMStrategy:
    """Semantic correlation via LLM — pluggable stub.

    TODO: embed alert summary + candidate incident titles, ask the model for
    a match. Requires an LLM endpoint config; out of scope for v1.
    """

    async def find_incident(
        self,
        db: AsyncSession,
        alert: NormalizedAlert,
        group_key: str | None,
        *,
        now: datetime,
        window_seconds: int,
        tenant_id: uuid.UUID | None = None,
    ) -> Incident | None:
        logger.debug("LLMStrategy stub: no-op")
        return None
