"""SAML login INITIATION (outbound) — complements the inbound ACS tests in
test_saml_acs.py. Covers everything up to the redirect to the IdP: the
AuthnRequest build + SP metadata. The actual IdP authentication + assertion
round-trip needs a live IdP and is deferred (inbound half is covered by the
signed-fixture ACS tests)."""

import base64
import zlib
from urllib.parse import parse_qs, urlparse

import pytest
from lxml import etree

from tests.saml.conftest import ACS_URL, IDP_SSO, NS, SP_ENTITY

pytestmark = pytest.mark.asyncio

MD = "{urn:oasis:names:tc:SAML:2.0:metadata}"


def _inflate_saml_request(saml_request_b64: str) -> bytes:
    """HTTP-Redirect binding: base64 + raw-DEFLATE."""
    return zlib.decompress(base64.b64decode(saml_request_b64), -15)


async def test_login_redirects_to_idp_with_authnrequest(client, enable_saml):
    r = await client.get("/api/v1/auth/saml/login", follow_redirects=False)
    assert r.status_code in (302, 303, 307), r.text

    loc = r.headers["location"]
    assert loc.startswith(IDP_SSO), loc  # redirect to the IdP SSO URL from metadata
    qs = parse_qs(urlparse(loc).query)
    assert "SAMLRequest" in qs  # HTTP-Redirect binding carries the request

    xml = _inflate_saml_request(qs["SAMLRequest"][0])
    doc = etree.fromstring(xml)
    assert doc.tag == "{urn:oasis:names:tc:SAML:2.0:protocol}AuthnRequest"
    # SP issuer = our entityID derived from ATLAS_PUBLIC_URL (/alert-hub subpath)
    assert doc.find("saml:Issuer", NS).text == SP_ENTITY
    # destination consistent with the IdP SSO URL; ACS points back at us
    assert doc.get("Destination") == IDP_SSO
    assert doc.get("AssertionConsumerServiceURL") == ACS_URL


async def test_login_disabled_refuses_cleanly(client):
    # default seeded config: enabled=False, no key/metadata -> 503, no IdP redirect
    r = await client.get("/api/v1/auth/saml/login", follow_redirects=False)
    assert r.status_code == 503


async def test_sp_metadata_endpoint(client, enable_saml):
    r = await client.get("/api/v1/auth/saml/metadata")
    assert r.status_code == 200
    doc = etree.fromstring(r.content)
    assert doc.tag == f"{MD}EntityDescriptor"
    assert doc.get("entityID") == SP_ENTITY  # /alert-hub subpath
    acs = doc.find(f".//{MD}AssertionConsumerService")
    assert acs is not None
    assert acs.get("Location") == ACS_URL
    assert acs.get("Binding") == "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
