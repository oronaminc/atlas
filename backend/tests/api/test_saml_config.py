"""SAML config (step a): seeded defaults + secret masking (PATCH with ******** must
not overwrite the stored private key)."""

import pytest

from app.core.security import decrypt_secret
from app.services.saml_config import get_saml_config

pytestmark = pytest.mark.asyncio


async def test_get_returns_seeded_defaults(client, admin_headers):
    r = await client.get("/api/v1/saml-config", headers=admin_headers)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["enabled"] is False
    assert d["display_name_attr"] == "givenName"
    assert d["uid_attr"] == "distinguishedName"
    assert d["email_attr"] == "mail"
    assert d["sp_private_key"] is None  # unset -> null, not masked


async def test_masked_key_patch_does_not_overwrite(client, db, admin_headers):
    await client.patch(
        "/api/v1/saml-config", json={"sp_private_key": "REAL-PRIVATE-KEY"}, headers=admin_headers
    )
    g1 = (await client.get("/api/v1/saml-config", headers=admin_headers)).json()["data"]
    assert g1["sp_private_key"] == "********"  # masked on read

    # echo the mask + flip enabled -> the stored key must survive
    await client.patch(
        "/api/v1/saml-config",
        json={"sp_private_key": "********", "enabled": True},
        headers=admin_headers,
    )
    row = await get_saml_config(db)
    assert decrypt_secret(row.sp_private_key) == "REAL-PRIVATE-KEY"
    g2 = (await client.get("/api/v1/saml-config", headers=admin_headers)).json()["data"]
    assert g2["enabled"] is True and g2["sp_private_key"] == "********"


async def test_patch_requires_admin(client, viewer_headers):
    r = await client.patch("/api/v1/saml-config", json={"enabled": True}, headers=viewer_headers)
    assert r.status_code == 403
