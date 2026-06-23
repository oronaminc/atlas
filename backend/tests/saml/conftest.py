"""SAML ACS test rig: a throwaway IdP keypair signs SAML 2.0 Responses shaped
exactly like the captured TiDC assertions (givenName / distinguishedName /
memberOf / optional mail), with NameIDFormat unspecified, audience = the SP
entityID derived from ATLAS_PUBLIC_URL (/alert-hub subpath). All offline."""

import base64
import datetime as dt

import pytest
import pytest_asyncio
import xmlsec
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from app.core.config import settings as app_settings

PUBLIC_URL = "https://atlas-dev.sktelecom.com/alert-hub"
ACS_URL = f"{PUBLIC_URL}/api/v1/auth/saml/acs"
SP_ENTITY = f"{PUBLIC_URL}/api/v1/auth/saml/metadata"
IDP_ENTITY = "https://tidcsso-dev.sktelecom.com"
IDP_SSO = "https://tidcsso-dev.sktelecom.com/v1/sso/saml2"

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}


def _gen_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return key_pem, cert_pem


def _pem_body(pem: str) -> str:
    return "".join(ln for ln in pem.strip().splitlines() if "-----" not in ln).strip()


def _idp_metadata(cert_pem: str) -> str:
    return (
        '<?xml version="1.0"?>'
        f'<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{IDP_ENTITY}">'
        '<IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        '<KeyDescriptor use="signing"><KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">'
        f"<X509Data><X509Certificate>{_pem_body(cert_pem)}</X509Certificate></X509Data>"
        "</KeyInfo></KeyDescriptor>"
        '<SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
        f'Location="{IDP_SSO}"/></IDPSSODescriptor></EntityDescriptor>'
    )


def _t(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sign_assertion(xml_bytes: bytes, key_pem: str, cert_pem: str) -> bytes:
    """Enveloped XML-DSig over the <Assertion> (RSA-SHA256, excl-c14n)."""
    root = etree.fromstring(xml_bytes)
    assertion = root.find("saml:Assertion", NS)
    assertion_id = assertion.get("ID")
    xmlsec.tree.add_ids(assertion, ["ID"])

    sig = xmlsec.template.create(assertion, xmlsec.Transform.EXCL_C14N, xmlsec.Transform.RSA_SHA256)
    # Schema: Signature must follow <Issuer> (the first child of Assertion).
    assertion.find("saml:Issuer", NS).addnext(sig)
    ref = xmlsec.template.add_reference(sig, xmlsec.Transform.SHA256, uri=f"#{assertion_id}")
    xmlsec.template.add_transform(ref, xmlsec.Transform.ENVELOPED)
    xmlsec.template.add_transform(ref, xmlsec.Transform.EXCL_C14N)
    key_info = xmlsec.template.ensure_key_info(sig)
    x509_data = xmlsec.template.add_x509_data(key_info)
    xmlsec.template.x509_data_add_certificate(x509_data)

    ctx = xmlsec.SignatureContext()
    key = xmlsec.Key.from_memory(key_pem.encode(), xmlsec.KeyFormat.PEM)
    key.load_cert_from_memory(cert_pem.encode(), xmlsec.KeyFormat.CERT_PEM)
    ctx.key = key
    ctx.sign(sig)
    return etree.tostring(root)


def _build_response(
    idp_key_pem: str,
    idp_cert_pem: str,
    *,
    attrs: dict[str, str],
    audience: str = SP_ENTITY,
    not_on_or_after: dt.datetime | None = None,
    tamper: bool = False,
) -> str:
    now = dt.datetime.now(dt.UTC)
    noa = not_on_or_after or (now + dt.timedelta(minutes=5))
    nbf = now - dt.timedelta(minutes=5)
    attr_xml = "".join(
        f'<saml:Attribute Name="{k}">'
        f"<saml:AttributeValue>{v}</saml:AttributeValue></saml:Attribute>"
        for k, v in attrs.items()
    )
    nameid = attrs.get("distinguishedName", "CN=unknown")
    xml = (
        '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="_resp1" Version="2.0" IssueInstant="{_t(now)}" Destination="{ACS_URL}">'
        f"<saml:Issuer>{IDP_ENTITY}</saml:Issuer>"
        "<samlp:Status><samlp:StatusCode "
        'Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
        f'<saml:Assertion ID="_assert1" Version="2.0" IssueInstant="{_t(now)}">'
        f"<saml:Issuer>{IDP_ENTITY}</saml:Issuer>"
        "<saml:Subject>"
        '<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified">'
        f"{nameid}</saml:NameID>"
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData Recipient="{ACS_URL}" NotOnOrAfter="{_t(noa)}"/>'
        "</saml:SubjectConfirmation></saml:Subject>"
        f'<saml:Conditions NotBefore="{_t(nbf)}" NotOnOrAfter="{_t(noa)}">'
        f"<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience>"
        "</saml:AudienceRestriction></saml:Conditions>"
        '<saml:AuthnStatement AuthnInstant="' + _t(now) + '">'
        "<saml:AuthnContext><saml:AuthnContextClassRef>"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:unspecified"
        "</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>"
        f"<saml:AttributeStatement>{attr_xml}</saml:AttributeStatement>"
        "</saml:Assertion></samlp:Response>"
    )
    signed = _sign_assertion(xml.encode(), idp_key_pem, idp_cert_pem)
    if tamper:
        doc = etree.fromstring(signed)
        sv = doc.find(".//ds:SignatureValue", NS)
        sv.text = ("A" if sv.text[0] != "A" else "B") + sv.text[1:]  # break the signature
        signed = etree.tostring(doc)
    return base64.b64encode(signed).decode()


@pytest.fixture(scope="session")
def idp_keypair() -> tuple[str, str]:
    return _gen_keypair()


@pytest.fixture(scope="session")
def sp_keypair() -> tuple[str, str]:
    return _gen_keypair()


@pytest.fixture(autouse=True)
def _public_url(monkeypatch):
    monkeypatch.setattr(app_settings, "ATLAS_PUBLIC_URL", PUBLIC_URL)


@pytest_asyncio.fixture
async def enable_saml(client, admin_headers, idp_keypair, sp_keypair):
    """Persist an enabled saml_config via the real admin PATCH (encrypts the SP key)."""
    idp_key, idp_cert = idp_keypair
    sp_key, sp_cert = sp_keypair
    r = await client.patch(
        "/api/v1/saml-config",
        json={
            "enabled": True,
            "sp_private_key": sp_key,
            "sp_certificate": sp_cert,
            "idp_metadata_xml": _idp_metadata(idp_cert),
        },
        headers=admin_headers,
    )
    assert r.status_code == 200
    return {"idp_key": idp_key, "idp_cert": idp_cert}


@pytest.fixture
def make_response(idp_keypair):
    idp_key, idp_cert = idp_keypair

    def _make(**kwargs) -> str:
        return _build_response(idp_key, idp_cert, **kwargs)

    return _make


# Captured TiDC attribute sets (real names).
ATTRS_WITH_EMAIL = {
    "givenName": "Hong Gildong",
    "distinguishedName": "CN=Hong Gildong,OU=Dev,DC=skt,DC=com",
    "memberOf": "CN=atlas-admins,OU=Groups,DC=skt,DC=com",
    "mail": "gildong@skt.com",
}
ATTRS_NO_EMAIL = {
    "givenName": "Hong Gildong",
    "distinguishedName": "CN=Hong Gildong,OU=Dev,DC=skt,DC=com",
    "memberOf": "CN=atlas-admins,OU=Groups,DC=skt,DC=com",
}
ATTRS_KOREAN_CN = {
    "givenName": "홍길동",
    "distinguishedName": "CN=홍길동,OU=Dev,DC=skt,DC=com",
    "memberOf": "CN=atlas-admins,OU=Groups,DC=skt,DC=com",
}
