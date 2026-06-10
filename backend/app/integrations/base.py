import asyncio
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 0.5


def make_client(base_url: str) -> httpx.AsyncClient:
    """All observability-stack clients are created here so the tenant header
    is injected exactly once. Individual calls must NOT set it again."""
    return httpx.AsyncClient(
        base_url=base_url,
        headers={"X-Scope-OrgID": settings.MIMIR_TENANT_ID},  # = "system"
        timeout=10.0,
    )


class BaseIntegrationClient:
    """Shared retry/backoff wrapper around httpx for external calls."""

    def __init__(self, base_url: str) -> None:
        self._client = make_client(base_url)

    async def request(
        self,
        method: str,
        path: str,
        *,
        retries: int = MAX_RETRIES,
        **kwargs: Any,
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                response = await self._client.request(method, path, **kwargs)
                # Retry server-side errors; client errors are surfaced as-is.
                if response.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"server error {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                else:
                    return response
            except httpx.TransportError as exc:
                last_exc = exc
            if attempt < retries - 1:
                await asyncio.sleep(BACKOFF_BASE_SECONDS * (2**attempt))
        assert last_exc is not None
        logger.error("integration call failed after %d attempts: %s", retries, last_exc)
        raise last_exc

    async def aclose(self) -> None:
        await self._client.aclose()
