"""Admin CRUD for the default per-incident channel toggles (IMP §7) applied to
new incidents at creation. Single row."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_admin
from app.core.envelope import envelope
from app.db import get_db
from app.models import User
from app.services.audit import record_audit
from app.services.grouping_config import get_notification_defaults

router = APIRouter(prefix="/notification-defaults", tags=["notification-defaults"])


class DefaultsOut(BaseModel):
    model_config = {"from_attributes": True}
    default_email: bool
    default_telegram: bool
    default_oncall: bool


class DefaultsUpdate(BaseModel):
    default_email: bool | None = None
    default_telegram: bool | None = None
    default_oncall: bool | None = None


@router.get("")
async def get_defaults(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    nd = await get_notification_defaults(db)
    await db.commit()
    return envelope(DefaultsOut.model_validate(nd).model_dump())


@router.patch("")
async def update_defaults(
    body: DefaultsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    nd = await get_notification_defaults(db)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(nd, k, v)
    await record_audit(
        db,
        actor_id=user.id,
        action="update",
        resource_type="notification_defaults",
        resource_id=nd.id,
        after=data,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(nd)
    return envelope(DefaultsOut.model_validate(nd).model_dump())
