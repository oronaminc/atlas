"""Channel assignment (admin): per-group notification channels — each group's
own telegram bot+chats, emails, oncall webhook. Secrets Fernet-encrypted at rest
and MASKED in responses. This is the piece that makes incidents actually deliver:
fanout routes incident -> groups mapped to its l2 -> these channels."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_admin
from app.core.envelope import envelope
from app.core.security import encrypt_secret
from app.db import get_db
from app.models import Group, User
from app.models.delivery import GroupChannel
from app.schemas.delivery import MASKED, GroupChannelCreate, GroupChannelOut
from app.services.audit import record_audit

router = APIRouter(tags=["channels"])


def _out(gc: GroupChannel) -> dict:
    return GroupChannelOut(
        id=gc.id,
        channel=gc.channel,
        enabled=gc.enabled,
        chat_id=gc.chat_id,
        email=gc.email,
        bot_token=MASKED if gc.bot_token else None,
        webhook_url=MASKED if gc.webhook_url else None,
        oncall_token=MASKED if gc.oncall_token else None,
    ).model_dump(mode="json")


@router.get("/groups/{group_id}/channels")
async def list_group_channels(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = (
        await db.execute(select(GroupChannel).where(GroupChannel.group_id == group_id))
    ).scalars()
    return envelope([_out(gc) for gc in rows])


@router.post("/groups/{group_id}/channels", status_code=201)
async def add_group_channel(
    group_id: uuid.UUID,
    body: GroupChannelCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if await db.get(Group, group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")
    gc = GroupChannel(
        group_id=group_id,
        channel=body.channel,
        enabled=body.enabled,
        chat_id=body.chat_id,
        email=body.email,
        bot_token=encrypt_secret(body.bot_token) if body.bot_token else None,
        webhook_url=encrypt_secret(body.webhook_url) if body.webhook_url else None,
        oncall_token=encrypt_secret(body.oncall_token) if body.oncall_token else None,
        created_by=admin.id,
    )
    db.add(gc)
    await db.flush()
    await record_audit(
        db,
        actor_id=admin.id,
        action="create",
        resource_type="group_channel",
        resource_id=gc.id,
        after={"group_id": str(group_id), "channel": body.channel},
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(gc)
    return envelope(_out(gc))


@router.delete("/channels/{channel_id}")
async def delete_group_channel(
    channel_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    gc = await db.get(GroupChannel, channel_id)
    if gc is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    await db.delete(gc)
    await record_audit(
        db,
        actor_id=admin.id,
        action="delete",
        resource_type="group_channel",
        resource_id=channel_id,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})
