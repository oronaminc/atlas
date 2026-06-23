"""SAML SP helpers: build python3-saml settings from the DB config, adapt the
FastAPI request for OneLogin, and JIT-provision the user from the assertion.

Attribute names are admin-configured (TiDC defaults: givenName / distinguishedName
/ mail). memberOf is intentionally ignored this phase. ACS signature/audience/
expiry validation is delegated to OneLogin_Saml2_Auth.process_response()."""

import hashlib
import re
from typing import Any
from urllib.parse import urlparse

from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_secret
from app.models import User
from app.models.base import utcnow
from app.models.saml import SamlConfig
from app.models.user import AuthProvider, GlobalRole


class SamlError(Exception):
    """Assertion is structurally valid but unusable (e.g. missing UID)."""


# --- SP identifiers (subpath-aware: ATLAS_PUBLIC_URL already carries /alert-hub) ---
def sp_entity_id() -> str:
    return f"{settings.ATLAS_PUBLIC_URL.rstrip('/')}/api/v1/auth/saml/metadata"


def sp_acs_url() -> str:
    return f"{settings.ATLAS_PUBLIC_URL.rstrip('/')}/api/v1/auth/saml/acs"


def _pem_body(pem: str) -> str:
    """Strip PEM headers/whitespace -> the base64 body python3-saml settings want."""
    return "".join(
        line for line in pem.strip().splitlines() if line and "-----" not in line
    ).strip()


def build_saml_settings(cfg: SamlConfig) -> dict[str, Any]:
    """python3-saml settings dict from the DB row. IdP entityID/SSO/cert come from
    the admin-pasted metadata XML; SP key/cert from the (decrypted) config."""
    idp = OneLogin_Saml2_IdPMetadataParser.parse(cfg.idp_metadata_xml or "")
    sp_key = decrypt_secret(cfg.sp_private_key) if cfg.sp_private_key else ""
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": sp_entity_id(),
            "assertionConsumerService": {
                "url": sp_acs_url(),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified",
            "x509cert": _pem_body(cfg.sp_certificate or ""),
            "privateKey": _pem_body(sp_key),
        },
        "idp": idp.get("idp", {}),
        "security": {
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "wantNameId": False,
            "requestedAuthnContext": False,
            "rejectUnsolicitedResponsesWithInResponseTo": False,
        },
    }


def _onelogin_base(path_suffix: str) -> dict[str, Any]:
    pub = urlparse(settings.ATLAS_PUBLIC_URL)
    return {
        "https": "on" if pub.scheme == "https" else "off",
        "http_host": pub.netloc,
        "script_name": pub.path.rstrip("/") + path_suffix,
    }


def login_request_data() -> dict[str, Any]:
    data = _onelogin_base("/api/v1/auth/saml/login")
    data.update({"get_data": {}, "post_data": {}})
    return data


def acs_request_data(saml_response: str, relay_state: str = "") -> dict[str, Any]:
    data = _onelogin_base("/api/v1/auth/saml/acs")
    data.update(
        {"get_data": {}, "post_data": {"SAMLResponse": saml_response, "RelayState": relay_state}}
    )
    return data


# --- JIT user provisioning ---
def _first(attrs: dict[str, list[str]], name: str) -> str | None:
    v = attrs.get(name)
    return v[0] if v else None


def _cn(dn: str) -> str:
    m = re.match(r"\s*CN=([^,]+)", dn, re.IGNORECASE)
    return m.group(1).strip() if m else dn


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _fallback_handle(saml_uid: str) -> str:
    return f"saml-{hashlib.sha1(saml_uid.encode()).hexdigest()[:8]}"


def synth_email(saml_uid: str) -> str:
    """Deterministic, unique, non-routable email when the IdP sends no mail —
    satisfies User.email NOT NULL + unique without ever colliding."""
    return f"saml-{hashlib.sha1(saml_uid.encode()).hexdigest()[:16]}@saml.invalid"


async def _unique_handle(db: AsyncSession, saml_uid: str) -> str:
    """Stable login handle derived from the DN's CN. Non-ASCII CNs (e.g. Korean)
    slugify to empty -> fall back to a deterministic saml-<sha1[:8]> handle so the
    username is never empty/invalid. Suffix on collision."""
    base = _slug(_cn(saml_uid)) or _fallback_handle(saml_uid)
    handle = base
    n = 2
    while (
        await db.execute(select(User).where(User.username == handle))
    ).scalar_one_or_none() is not None:
        handle = f"{base}-{n}"
        n += 1
    return handle


async def jit_user(
    db: AsyncSession, cfg: SamlConfig, attrs: dict[str, list[str]], nameid: str | None
) -> tuple[User, bool]:
    """Match on saml_uid (= distinguishedName); create with role=viewer on first
    login, else refresh display name only (role/email/username preserved).
    Returns (user, created)."""
    uid = _first(attrs, cfg.uid_attr) or nameid
    if not uid:
        raise SamlError("assertion missing UID attribute")
    display = _first(attrs, cfg.display_name_attr)
    email = _first(attrs, cfg.email_attr)

    user = (await db.execute(select(User).where(User.saml_uid == uid))).scalar_one_or_none()
    created = False
    if user is None:
        user = User(
            saml_uid=uid,
            username=await _unique_handle(db, uid),
            display_name=display,
            email=email or synth_email(uid),
            auth_provider=AuthProvider.saml,
            role=GlobalRole.viewer,
            hashed_password=None,
        )
        db.add(user)
        await db.flush()
        created = True
    else:
        user.display_name = display  # refresh display ONLY; role/email/username kept
    user.last_login_at = utcnow()
    return user, created
