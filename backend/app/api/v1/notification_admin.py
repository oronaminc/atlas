"""Admin notification management: settings (bot token/quotas), read-only
recipients list, and delivery-status listing. (Per-group routes were removed
in the IMP redesign — routing is by the incident's l2 -> user-group mapping.)"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_admin
from app.core.envelope import envelope
from app.core.security import encrypt_secret
from app.db import get_db
from app.models import User
from app.models.delivery import Notification
from app.notifications.settings import get_notification_settings
from app.schemas.delivery import (
    MASKED,
    NotificationOut,
    NotificationSettingsOut,
    NotificationSettingsUpdate,
    RecipientOut,
)
from app.services.audit import record_audit

router = APIRouter(tags=["notification-admin"])

SETTINGS_AUDIT_FIELDS = [
    "telegram_rate_per_second",
    "quota_group_per_hour",
    "quota_global_per_day",
    "pending_softcap",
]


def settings_out(row) -> dict:
    return NotificationSettingsOut(
        telegram_bot_token=MASKED if row.telegram_bot_token else None,
        telegram_rate_per_second=row.telegram_rate_per_second,
        quota_group_per_hour=row.quota_group_per_hour,
        quota_global_per_day=row.quota_global_per_day,
        pending_softcap=row.pending_softcap,
    ).model_dump(mode="json")


def _settings_snapshot(row) -> dict:
    snap = {f: getattr(row, f) for f in SETTINGS_AUDIT_FIELDS}
    snap["telegram_bot_token_set"] = bool(row.telegram_bot_token)
    return snap


@router.get("/notification-settings")
async def read_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await get_notification_settings(db)
    await db.commit()
    return envelope(settings_out(row))


@router.patch("/notification-settings")
async def update_settings(
    body: NotificationSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = await get_notification_settings(db)
    before = _settings_snapshot(row)
    data = body.model_dump(exclude_unset=True)
    token = data.pop("telegram_bot_token", MASKED)
    if token != MASKED:
        row.telegram_bot_token = encrypt_secret(token) if token else None
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="notification_settings",
        resource_id=row.id,
        before=before,
        after=_settings_snapshot(row),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(row)
    return envelope(settings_out(row))


# --- recipients (admin, view-only) ---


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


# --- delivery status ---


@router.get("/notifications")
async def list_notifications(
    incident_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if incident_id is not None:
        stmt = stmt.where(Notification.incident_id == incident_id)
    if status is not None:
        stmt = stmt.where(Notification.status == status)
    res = await db.execute(stmt)
    return envelope(
        [NotificationOut.model_validate(n).model_dump(mode="json") for n in res.scalars().unique()]
    )
