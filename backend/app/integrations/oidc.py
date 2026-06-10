"""Minimal OIDC (authorization-code flow) client for the in-house SSO."""

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class OIDCClient:
    def __init__(self) -> None:
        self._discovery: dict[str, Any] | None = None

    async def _discover(self) -> dict[str, Any]:
        if self._discovery is None:
            url = f"{settings.OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                self._discovery = response.json()
        return self._discovery

    async def authorization_url(self, state: str) -> str:
        discovery = await self._discover()
        params = urlencode(
            {
                "response_type": "code",
                "client_id": settings.OIDC_CLIENT_ID,
                "redirect_uri": settings.OIDC_REDIRECT_URI,
                "scope": "openid profile email",
                "state": state,
            }
        )
        return f"{discovery['authorization_endpoint']}?{params}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        discovery = await self._discover()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                discovery["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.OIDC_REDIRECT_URI,
                    "client_id": settings.OIDC_CLIENT_ID,
                    "client_secret": settings.OIDC_CLIENT_SECRET,
                },
            )
            response.raise_for_status()
            return response.json()

    async def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        discovery = await self._discover()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                discovery["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()


oidc_client = OIDCClient()
