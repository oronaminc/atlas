"""Notification read APIs: recipients list + delivery-status listing.
(Global notification-settings were removed — channels are per-group; see the
channel-assignment API in groups.py / channels.py.)"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.models.delivery import Notification
from app.schemas.delivery import NotificationOut, RecipientOut

router = APIRouter(tags=["notification-admin"])


@router.get("/notification-recipients")
async def list_recipients(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    res = await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.email))
    rows = [
        RecipientOut(
            user_id=u.id,
            username=u.username,
            email=u.email,
            telegram_chat_id=u.telegram_chat_id,
            groups=[m.group.name for m in u.memberships],
        ).model_dump(mode="json")
        for u in res.scalars().unique()
    ]
    return envelope(rows)


@router.get("/notifications")
async def list_notifications(
    incident_id: uuid.UUID | None = None,
    status: str | None = None,
    channel: str | None = None,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if incident_id is not None:
        stmt = stmt.where(Notification.incident_id == incident_id)
    if status is not None:
        stmt = stmt.where(Notification.status == status)
    if channel is not None:
        stmt = stmt.where(Notification.channel == channel)
    res = await db.execute(stmt)
    return envelope(
        [NotificationOut.model_validate(n).model_dump(mode="json") for n in res.scalars().unique()]
    )
