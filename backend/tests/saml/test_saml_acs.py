"""SAML ACS + JIT (steps b/c), fully offline against signed in-test assertions
using the real TiDC attribute names (givenName / distinguishedName / memberOf /
mail). httpx doesn't follow the post-login redirect target, so a 200/redirect with
the refresh cookie set == accepted; 400 == rejected."""

import datetime as dt

import pytest
from sqlalchemy import func, select

from app.models import User
from app.models.user import AuthProvider, GlobalRole
from tests.saml.conftest import ATTRS_KOREAN_CN, ATTRS_NO_EMAIL, ATTRS_WITH_EMAIL

pytestmark = pytest.mark.asyncio


async def _post_acs(client, saml_response: str):
    return await client.post(
        "/api/v1/auth/saml/acs",
        data={"SAMLResponse": saml_response},
        follow_redirects=False,
    )


def _accepted(r) -> bool:
    return r.status_code in (302, 303, 307) and "atlas_refresh" in r.headers.get("set-cookie", "")


async def _count_users(db) -> int:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


# 1 — first login creates ONE viewer user with the captured attributes
async def test_first_login_creates_one_viewer(client, db, enable_saml, make_response):
    before = await _count_users(db)
    r = await _post_acs(client, make_response(attrs=ATTRS_WITH_EMAIL))
    assert _accepted(r), r.text
    assert await _count_users(db) == before + 1
    u = (
        await db.execute(select(User).where(User.saml_uid == ATTRS_WITH_EMAIL["distinguishedName"]))
    ).scalar_one()
    assert u.role == GlobalRole.viewer
    assert u.auth_provider == AuthProvider.saml
    assert u.display_name == "Hong Gildong"  # givenName
    assert u.email == "gildong@skt.com"  # mail used
    assert u.hashed_password is None
    assert u.memberships == []  # memberOf ignored


# 2 — second login: same DN matches, no duplicate, display refreshed, role/email preserved
async def test_second_login_matches_and_preserves_role_email(
    client, db, enable_saml, make_response
):
    await _post_acs(client, make_response(attrs=ATTRS_WITH_EMAIL))
    u = (
        await db.execute(select(User).where(User.saml_uid == ATTRS_WITH_EMAIL["distinguishedName"]))
    ).scalar_one()
    # admin later promotes the user — must NOT be overwritten by a later SSO login
    u.role = GlobalRole.admin
    await db.commit()
    count_after_first = await _count_users(db)

    changed = dict(ATTRS_WITH_EMAIL, givenName="Hong G. Updated")
    r = await _post_acs(client, make_response(attrs=changed))
    assert _accepted(r), r.text
    assert await _count_users(db) == count_after_first  # no duplicate
    await db.refresh(u)
    assert u.display_name == "Hong G. Updated"  # display refreshed
    assert u.role == GlobalRole.admin  # admin-set role preserved
    assert u.email == "gildong@skt.com"  # email preserved


# 3 — no email attribute -> login still works via synthesized email
async def test_no_email_synthesizes_and_logs_in(client, db, enable_saml, make_response):
    r = await _post_acs(client, make_response(attrs=ATTRS_NO_EMAIL))
    assert _accepted(r), r.text
    u = (
        await db.execute(select(User).where(User.saml_uid == ATTRS_NO_EMAIL["distinguishedName"]))
    ).scalar_one()
    assert u.email and u.email.endswith("@saml.invalid")


# 4 — mail present -> used verbatim (not synthesized)
async def test_with_email_uses_mail(client, db, enable_saml, make_response):
    await _post_acs(client, make_response(attrs=ATTRS_WITH_EMAIL))
    u = (
        await db.execute(select(User).where(User.saml_uid == ATTRS_WITH_EMAIL["distinguishedName"]))
    ).scalar_one()
    assert u.email == "gildong@skt.com"


# 5 — tampered signature -> rejected, no user
async def test_tampered_signature_rejected(client, db, enable_saml, make_response):
    before = await _count_users(db)
    r = await _post_acs(client, make_response(attrs=ATTRS_WITH_EMAIL, tamper=True))
    assert r.status_code == 400
    assert await _count_users(db) == before


# 6 — expired assertion -> rejected
async def test_expired_rejected(client, db, enable_saml, make_response):
    past = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    r = await _post_acs(client, make_response(attrs=ATTRS_WITH_EMAIL, not_on_or_after=past))
    assert r.status_code == 400


# 7 — wrong audience -> rejected
async def test_wrong_audience_rejected(client, db, enable_saml, make_response):
    r = await _post_acs(
        client, make_response(attrs=ATTRS_WITH_EMAIL, audience="https://wrong.example/sp")
    )
    assert r.status_code == 400


# 8 — SAML disabled -> 503, no user
async def test_disabled_returns_503(client, db, make_response):
    before = await _count_users(db)
    r = await _post_acs(client, make_response(attrs=ATTRS_WITH_EMAIL))
    assert r.status_code == 503
    assert await _count_users(db) == before


# 9 — Korean CN slugifies to empty -> deterministic saml-<sha1[:8]> username
async def test_korean_cn_handle_fallback(client, db, enable_saml, make_response):
    r = await _post_acs(client, make_response(attrs=ATTRS_KOREAN_CN))
    assert _accepted(r), r.text
    u = (
        await db.execute(select(User).where(User.saml_uid == ATTRS_KOREAN_CN["distinguishedName"]))
    ).scalar_one()
    assert u.username.startswith("saml-") and len(u.username) == len("saml-") + 8
    assert u.username.isascii() and u.username.islower()
    assert u.display_name == "홍길동"  # display keeps the original non-ASCII name
