import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_user, require_admin, require_editor
from app.core.envelope import envelope
from app.core.pagination import decode_cursor, page_meta
from app.core.security import decrypt_secret, encrypt_secret
from app.db import get_db
from app.models import NotificationPolicy, Receiver, User
from app.schemas.notification import (
    PolicyCreate,
    PolicyOut,
    PolicyUpdate,
    ReceiverCreate,
    ReceiverOut,
    ReceiverUpdate,
)
from app.services.audit import record_audit

router = APIRouter(tags=["notifications"])

# Config keys treated as secrets: Fernet-encrypted at rest, masked in responses.
SECRET_KEYS = {"url", "webhook_url", "api_key", "routing_key", "password", "token"}
MASK = "********"


def get_alertmanager_client():
    from app.integrations.alertmanager import AlertmanagerClient

    return AlertmanagerClient()


def get_alertmanager_client_for_org(org: str | None):
    from app.integrations.alertmanager import AlertmanagerClient

    return AlertmanagerClient(org=org)


def _encrypt_config(config: dict) -> dict:
    return {
        k: encrypt_secret(str(v)) if k in SECRET_KEYS and v is not None else v
        for k, v in config.items()
    }


def _mask_config(config: dict) -> dict:
    return {k: MASK if k in SECRET_KEYS else v for k, v in config.items()}


def decrypted_config(receiver: Receiver) -> dict:
    """Plaintext config for pushing to Alertmanager / sending test messages."""
    out = {}
    for k, v in (receiver.config or {}).items():
        if k in SECRET_KEYS and isinstance(v, str):
            try:
                out[k] = decrypt_secret(v)
            except Exception:
                out[k] = v
        else:
            out[k] = v
    return out


def receiver_out(receiver: Receiver) -> dict:
    out = ReceiverOut.model_validate(receiver)
    out.config = _mask_config(receiver.config or {})
    return out.model_dump(mode="json")


# --- Receivers ---


@router.get("/receivers")
async def list_receivers(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Receiver).order_by(Receiver.created_at.desc(), Receiver.id.desc())
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            t, i = decoded
            stmt = stmt.where(
                or_(
                    Receiver.created_at < t,
                    (Receiver.created_at == t) & (Receiver.id < i),
                )
            )
    res = await db.execute(stmt.limit(limit + 1))
    items, meta = page_meta(list(res.scalars().unique()), limit)
    return envelope([receiver_out(r) for r in items], meta=meta)


@router.post("/receivers", status_code=201)
async def create_receiver(
    body: ReceiverCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    dup = await db.execute(select(Receiver).where(Receiver.name == body.name))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Receiver name already exists")
    receiver = Receiver(
        name=body.name,
        type=body.type,
        config=_encrypt_config(body.config),
        created_by=admin.id,
    )
    db.add(receiver)
    await db.flush()
    await record_audit(
        db,
        actor_id=admin.id,
        action="create",
        resource_type="receiver",
        resource_id=receiver.id,
        after={"name": receiver.name, "type": receiver.type.value},
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(receiver)
    return envelope(receiver_out(receiver))


@router.patch("/receivers/{receiver_id}")
async def update_receiver(
    receiver_id: uuid.UUID,
    body: ReceiverUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    receiver = await db.get(Receiver, receiver_id)
    if receiver is None:
        raise HTTPException(status_code=404, detail="Receiver not found")
    if body.name is not None:
        receiver.name = body.name
    if body.config is not None:
        # Masked values mean "keep the stored secret".
        merged = dict(receiver.config or {})
        for k, v in body.config.items():
            if v == MASK:
                continue
            merged[k] = encrypt_secret(str(v)) if k in SECRET_KEYS and v is not None else v
        receiver.config = merged
    receiver.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="receiver",
        resource_id=receiver.id,
        after={"name": receiver.name},
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(receiver)
    return envelope(receiver_out(receiver))


@router.delete("/receivers/{receiver_id}")
async def delete_receiver(
    receiver_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    receiver = await db.get(Receiver, receiver_id)
    if receiver is None:
        raise HTTPException(status_code=404, detail="Receiver not found")
    await db.delete(receiver)
    await record_audit(
        db,
        actor_id=admin.id,
        action="delete",
        resource_type="receiver",
        resource_id=receiver_id,
        before={"name": receiver.name, "type": receiver.type.value},
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})


@router.post("/receivers/{receiver_id}/test")
async def test_receiver(
    receiver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_editor),
):
    """Sends a test notification through the receiver's channel."""
    receiver = await db.get(Receiver, receiver_id)
    if receiver is None:
        raise HTTPException(status_code=404, detail="Receiver not found")
    config = decrypted_config(receiver)
    import httpx

    try:
        if receiver.type.value in ("slack", "webhook"):
            url = config.get("url") or config.get("webhook_url")
            if not url:
                raise HTTPException(status_code=400, detail="Receiver has no url configured")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json={"text": f"[Atlas] test notification for receiver '{receiver.name}'"},
                )
                response.raise_for_status()
        else:
            # TODO: email/pagerduty test delivery — requires SMTP / PD events API
            # credentials; wire up when those integrations are configured.
            raise HTTPException(
                status_code=501,
                detail=f"Test not implemented for type {receiver.type.value}",
            )
    except HTTPException:
        raise
    except Exception as exc:
        return envelope({"ok": False, "error": str(exc)})
    return envelope({"ok": True})


# --- Notification policies ---


@router.get("/notification-policies")
async def list_policies(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    res = await db.execute(
        select(NotificationPolicy).order_by(NotificationPolicy.created_at.desc())
    )
    return envelope(
        [PolicyOut.model_validate(p).model_dump(mode="json") for p in res.scalars().unique()]
    )


@router.post("/notification-policies", status_code=201)
async def create_policy(
    body: PolicyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    receiver = await db.get(Receiver, body.receiver_id)
    if receiver is None:
        raise HTTPException(status_code=404, detail="Receiver not found")
    policy = NotificationPolicy(
        matcher=body.matcher,
        receiver_id=body.receiver_id,
        group_by=body.group_by,
        repeat_interval=body.repeat_interval,
        created_by=admin.id,
    )
    db.add(policy)
    await db.flush()
    await record_audit(
        db,
        actor_id=admin.id,
        action="create",
        resource_type="notification_policy",
        resource_id=policy.id,
        after={"matcher": policy.matcher, "receiver_id": str(policy.receiver_id)},
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(policy)
    return envelope(PolicyOut.model_validate(policy).model_dump(mode="json"))


@router.patch("/notification-policies/{policy_id}")
async def update_policy(
    policy_id: uuid.UUID,
    body: PolicyUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    policy = await db.get(NotificationPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(policy, field, value)
    policy.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="notification_policy",
        resource_id=policy.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(policy)
    return envelope(PolicyOut.model_validate(policy).model_dump(mode="json"))


@router.delete("/notification-policies/{policy_id}")
async def delete_policy(
    policy_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    policy = await db.get(NotificationPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    await db.delete(policy)
    await record_audit(
        db,
        actor_id=admin.id,
        action="delete",
        resource_type="notification_policy",
        resource_id=policy_id,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})
