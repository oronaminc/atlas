import logging
import secrets
import uuid

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import client_ip, get_current_user, get_user_by_email
from app.core.envelope import envelope
from app.core.rate_limit import login_rate_limiter
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.db import get_db
from app.integrations.oidc import oidc_client
from app.models import User
from app.models.base import utcnow
from app.models.user import AuthProvider, GlobalRole
from app.schemas.auth import LoginRequest, PasswordChangeRequest
from app.schemas.user import GroupMembershipOut, UserOut
from app.services import saml_auth
from app.services.audit import record_audit
from app.services.saml_config import get_saml_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "atlas_refresh"
OIDC_STATE_COOKIE = "atlas_oidc_state"

# Browser-facing cookie path. Under a subpath deploy the ingress strips
# ROOT_PATH before the backend, but Set-Cookie path is what the BROWSER stores —
# it must carry the prefix or the cookie won't be sent on /<prefix>/api/v1/auth.
COOKIE_PATH = f"{settings.ROOT_PATH}/api/v1/auth"


def user_to_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.groups = [
        GroupMembershipOut(
            group_id=m.group_id,
            group_name=m.group.name,
            role_in_group=m.role_in_group,
        )
        for m in user.memberships
    ]
    return out


def set_refresh_cookie(response: Response, user_id: uuid.UUID) -> None:
    token = create_token(user_id, "refresh")
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,  # type: ignore[arg-type]  # CSRF protection
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path=COOKIE_PATH,
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    ip = client_ip(request) or "unknown"
    allowed = await login_rate_limiter.hit(
        f"login:{ip}:{body.email}",
        settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts, try again later",
        )

    user = await get_user_by_email(db, body.email)
    if (
        user is None
        or not user.is_active
        or user.hashed_password is None
        or not verify_password(body.password, user.hashed_password)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user.last_login_at = utcnow()
    await record_audit(
        db,
        actor_id=user.id,
        action="login",
        resource_type="user",
        resource_id=user.id,
        ip=ip,
    )
    await db.commit()

    set_refresh_cookie(response, user.id)
    return envelope({"access_token": create_token(user.id, "access"), "token_type": "bearer"})


@router.post("/refresh")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = decode_token(token, "refresh")
        user_id = uuid.UUID(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, ValueError) as e:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from e

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Rotate the refresh token on every use.
    set_refresh_cookie(response, user.id)
    return envelope({"access_token": create_token(user.id, "access"), "token_type": "bearer"})


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return envelope({"ok": True})


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return envelope(user_to_out(user).model_dump(mode="json"))


@router.post("/me/password")
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.auth_provider != AuthProvider.local or user.hashed_password is None:
        raise HTTPException(status_code=400, detail="SSO accounts cannot change password here")
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user.hashed_password = hash_password(body.new_password)
    await record_audit(
        db,
        actor_id=user.id,
        action="password_change",
        resource_type="user",
        resource_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return envelope({"ok": True})


# --- OIDC (authorization-code flow with the in-house SSO) ---


@router.get("/oidc/login")
async def oidc_login(response: Response):
    if not settings.OIDC_ISSUER:
        raise HTTPException(status_code=503, detail="OIDC is not configured")
    state = secrets.token_urlsafe(24)
    url = await oidc_client.authorization_url(state)
    redirect = RedirectResponse(url)
    redirect.set_cookie(
        OIDC_STATE_COOKIE,
        state,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",  # lax (not strict): the OIDC provider redirects back cross-site
        max_age=600,
        path=COOKIE_PATH,
    )
    return redirect


@router.get("/oidc/callback")
async def oidc_callback(
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    expected_state = request.cookies.get(OIDC_STATE_COOKIE)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(status_code=400, detail="Invalid OIDC state")

    tokens = await oidc_client.exchange_code(code)
    userinfo = await oidc_client.fetch_userinfo(tokens["access_token"])
    sub = userinfo.get("sub")
    email = userinfo.get("email")
    if not sub or not email:
        raise HTTPException(status_code=400, detail="OIDC userinfo missing sub/email")

    user = await get_user_by_email(db, email)
    if user is None:
        user = User(
            email=email,
            username=userinfo.get("preferred_username") or email.split("@")[0],
            auth_provider=AuthProvider.oidc,
            oidc_sub=sub,
            role=GlobalRole.viewer,
        )
        db.add(user)
        await db.flush()
        await record_audit(
            db,
            actor_id=user.id,
            action="oidc_signup",
            resource_type="user",
            resource_id=user.id,
            ip=client_ip(request),
        )
    elif user.oidc_sub is None:
        user.oidc_sub = sub

    user.last_login_at = utcnow()
    await record_audit(
        db,
        actor_id=user.id,
        action="oidc_login",
        resource_type="user",
        resource_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()

    redirect = RedirectResponse(settings.FRONTEND_URL)
    set_refresh_cookie(redirect, user.id)
    redirect.delete_cookie(OIDC_STATE_COOKIE, path=COOKIE_PATH)
    return redirect


# --- SAML 2.0 (SP-side; config is admin-managed in saml_config) ---


def _saml_enabled(cfg) -> bool:
    return bool(cfg.enabled and cfg.idp_metadata_xml)


@router.get("/saml/login")
async def saml_login(db: AsyncSession = Depends(get_db)):
    """Build an AuthnRequest and redirect to the IdP SSO URL (HTTP-Redirect)."""
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    cfg = await get_saml_config(db)
    if not _saml_enabled(cfg):
        raise HTTPException(status_code=503, detail="SAML is not configured")
    auth = OneLogin_Saml2_Auth(
        saml_auth.login_request_data(), old_settings=saml_auth.build_saml_settings(cfg)
    )
    return RedirectResponse(auth.login(return_to=settings.FRONTEND_URL))


@router.post("/saml/acs")
async def saml_acs(request: Request, db: AsyncSession = Depends(get_db)):
    """Assertion Consumer Service. python3-saml validates the assertion signature
    (against the IdP cert in the metadata), audience, NotOnOrAfter, and
    destination; then JIT-provision the user (role=viewer on first login)."""
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    cfg = await get_saml_config(db)
    if not _saml_enabled(cfg) or not cfg.sp_private_key:
        raise HTTPException(status_code=503, detail="SAML is not configured")

    form = await request.form()
    saml_response = str(form.get("SAMLResponse") or "")
    relay_state = str(form.get("RelayState") or "")
    auth = OneLogin_Saml2_Auth(
        saml_auth.acs_request_data(saml_response, relay_state),
        old_settings=saml_auth.build_saml_settings(cfg),
    )
    auth.process_response()
    errors = auth.get_errors()
    if errors or not auth.is_authenticated():
        logger.warning(
            "SAML ACS rejected: errors=%s reason=%s", errors, auth.get_last_error_reason()
        )
        raise HTTPException(status_code=400, detail="SAML assertion rejected")

    attrs = auth.get_attributes()
    # Attribute dump on success (operational visibility only; NOT a verification path).
    logger.info("SAML assertion accepted; attributes=%s", sorted(attrs.keys()))
    try:
        user, created = await saml_auth.jit_user(db, cfg, attrs, auth.get_nameid())
    except saml_auth.SamlError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await record_audit(
        db,
        actor_id=user.id,
        action="saml_signup" if created else "saml_login",
        resource_type="user",
        resource_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()

    redirect = RedirectResponse(settings.FRONTEND_URL)
    set_refresh_cookie(redirect, user.id)
    return redirect


@router.get("/saml/metadata")
async def saml_metadata(db: AsyncSession = Depends(get_db)):
    """SP metadata (for handing to the IdP admin)."""
    from onelogin.saml2.settings import OneLogin_Saml2_Settings

    cfg = await get_saml_config(db)
    saml_settings = OneLogin_Saml2_Settings(
        saml_auth.build_saml_settings(cfg), sp_validation_only=True
    )
    return Response(content=saml_settings.get_sp_metadata(), media_type="application/xml")
