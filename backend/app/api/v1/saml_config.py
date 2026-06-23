"""Admin config for SAML SSO (single row). sp_private_key Fernet-encrypted +
MASKED in responses; only overwritten when a non-masked value is submitted.
Audited. Login/ACS live in auth.py; this only stores the config."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, require_admin
from app.core.envelope import envelope
from app.core.security import encrypt_secret
from app.db import get_db
from app.models import User
from app.models.saml import SamlConfig
from app.schemas.delivery import MASKED
from app.services.audit import record_audit
from app.services.saml_config import get_saml_config

router = APIRouter(prefix="/saml-config", tags=["saml"])

AUDIT_FIELDS = ["enabled", "display_name_attr", "uid_attr", "email_attr"]


class SamlConfigUpdate(BaseModel):
    enabled: bool | None = None
    sp_private_key: str | None = None
    sp_certificate: str | None = None
    idp_metadata_xml: str | None = None
    display_name_attr: str | None = None
    uid_attr: str | None = None
    email_attr: str | None = None


def _out(row: SamlConfig) -> dict:
    return {
        "enabled": row.enabled,
        "sp_private_key": MASKED if row.sp_private_key else None,  # secret never echoed
        "sp_certificate": row.sp_certificate,
        "idp_metadata_xml": row.idp_metadata_xml,
        "display_name_attr": row.display_name_attr,
        "uid_attr": row.uid_attr,
        "email_attr": row.email_attr,
    }


def _snapshot(row: SamlConfig) -> dict:
    snap = {f: getattr(row, f) for f in AUDIT_FIELDS}
    snap["sp_private_key_set"] = bool(row.sp_private_key)
    snap["sp_certificate_set"] = bool(row.sp_certificate)
    snap["idp_metadata_set"] = bool(row.idp_metadata_xml)
    return snap


@router.get("")
async def read_config(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    row = await get_saml_config(db)
    await db.commit()
    return envelope(_out(row))


@router.patch("")
async def update_config(
    body: SamlConfigUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = await get_saml_config(db)
    before = _snapshot(row)
    data = body.model_dump(exclude_unset=True)
    # Secret: only update when a non-masked value is submitted (don't clobber).
    key = data.pop("sp_private_key", MASKED)
    if key != MASKED:
        row.sp_private_key = encrypt_secret(key) if key else None
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_by = admin.id
    await record_audit(
        db,
        actor_id=admin.id,
        action="update",
        resource_type="saml_config",
        resource_id=row.id,
        before=before,
        after=_snapshot(row),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(row)
    return envelope(_out(row))
