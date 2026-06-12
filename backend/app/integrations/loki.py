"""Loki client — used for LogQL rule previews."""

from typing import Any

from app.core.config import settings
from app.integrations.base import BaseIntegrationClient


class LokiClient(BaseIntegrationClient):
    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url or settings.LOKI_URL)

    async def instant_query(self, expr: str) -> dict[str, Any]:
        response = await self.request(
            "GET", "/loki/api/v1/query", params={"query": expr}
        )
        response.raise_for_status()
        return response.json()
