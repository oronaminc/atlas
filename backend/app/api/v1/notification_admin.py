"""Admin notification management: settings (bot token/quotas), per-group
routes, read-only recipients list, and delivery-status listing."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_admin
from app.core.envelope import envelope
from app.core.security import encrypt_secret
from app.core.tenancy import resolve_tenant_slug
from app.db import get_db
from app.models import Group, User
from app.models.delivery import Notification, NotificationRoute
from app.notifications.settings import get_notification_settings
from app.schemas.delivery import (
    MASKED,
    NotificationOut,
    NotificationSettingsOut,
    NotificationSettingsUpdate,
    RecipientOut,
    RouteCreate,
    RouteOut,
    RouteUpdate,
)
from app.services.audit import record_audit

router = APIRouter(tags=["notification-admin"])

SETTINGS_AUDIT_FIELDS = [
    "telegram_rate_per_second",
    "quota_group_per_hour",
    "quota_global_per_day",
]


async def settings_tenant_id(
    tenant: str | None = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> uuid.UUID | None:
    """Which tenant's notification settings row to read/write. Tenant-admins
    always get their own; HQ picks via ?tenant=<slug> (none = legacy row)."""
    if admin.tenant_id is not None:
        return admin.tenant_id
    if tenant:
        target = await resolve_tenant_slug(db, tenant)
        if target is None:
            raise HTTPException(status_code=404, detail="Unknown tenant")
        return target.id
    return None


def settings_out(row) -> dict:
    return NotificationSettingsOut(
        telegram_bot_token=MASKED if row.telegram_bot_token else None,
        telegram_rate_per_second=row.telegram_rate_per_second,
        quota_group_per_hour=row.quota_group_per_hour,
        quota_global_per_day=row.quota_global_per_day,
    ).model_dump(mode="json")


def _settings_snapshot(row) -> dict:
    snap = {f: getattr(row, f) for f in SETTINGS_AUDIT_FIELDS}
    snap["telegram_bot_token_set"] = bool(row.telegram_bot_token)
    return snap


@router.get("/notification-settings")
async def read_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
    tenant_id: uuid.UUID | None = Depends(settings_tenant_id),
):
    row = await get_notification_settings(db, tenant_id)
    await db.commit()
    return envelope(settings_out(row))


@router.patch("/notification-settings")
async def update_settings(
    body: NotificationSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
    tenant_id: uuid.UUID | None = Depends(settings_tenant_id),
):
    row = await get_notification_settings(db, tenant_id)
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


# --- routes (one per group) ---


@router.get("/notification-routes")
async def list_routes(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    res = await db.execute(select(NotificationRoute).order_by(NotificationRoute.created_at))
    return envelope([RouteOut.model_validate(r).model_dump(mode="json") for r in res.scalars()])


@router.post("/notification-routes", status_code=201)
async def create_route(
    body: RouteCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    group = await db.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    dup = await db.execute(
        select(NotificationRoute).where(NotificationRoute.group_id == body.group_id)
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Route for this group already exists")
    # route belongs to the target group's tenant (fanout matches on it)
    route = NotificationRoute(**body.model_dump(), tenant_id=group.tenant_id, created_by=admin.id)
    db.add(route)
    await db.flush()
    await record_audit(
        db,
        actor_id=admin.id,
        action="create",
        resource_type="notification_route",
        resource_id=route.id,
        after={"group_id": str(body.group_id), "channels": body.channels},
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(route)
    return envelope(RouteOut.model_validate(route).model_dump(mode="json"))


@router.patch("/notification-routes/{route_id}")
async def update_route(
    route_id: uuid.UUID,
    body: RouteUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    route = await db.get(NotificationRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(route, field, value)
    route.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="notification_route",
        resource_id=route.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(route)
    return envelope(RouteOut.model_validate(route).model_dump(mode="json"))


@router.delete("/notification-routes/{route_id}")
async def delete_route(
    route_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    route = await db.get(NotificationRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    await db.delete(route)
    await record_audit(
        db,
        actor_id=admin.id,
        action="delete",
        resource_type="notification_route",
        resource_id=route_id,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})


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
