"""Mimir Alertmanager client.

Uses the Mimir multi-tenant Alertmanager APIs:
  - config:   GET/POST /api/v1/alerts  (alertmanager config YAML, tenant-scoped)
  - alerts:   GET /alertmanager/api/v2/alerts
  - silences: GET/POST /alertmanager/api/v2/silences, DELETE /silence/<id>
"""

from typing import Any

import yaml

from app.core.config import settings
from app.integrations.base import BaseIntegrationClient


class AlertmanagerClient(BaseIntegrationClient):
    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url or settings.MIMIR_ALERTMANAGER_URL)

    # --- config (routing / receivers) ---

    async def set_config(
        self, config: dict[str, Any], templates: dict[str, str] | None = None
    ) -> None:
        payload = {
            "alertmanager_config": yaml.safe_dump(config, sort_keys=False),
            "template_files": templates or {},
        }
        response = await self.request(
            "POST",
            "/api/v1/alerts",
            content=yaml.safe_dump(payload, sort_keys=False),
            headers={"Content-Type": "application/yaml"},
        )
        response.raise_for_status()

    async def get_config(self) -> dict[str, Any]:
        response = await self.request("GET", "/api/v1/alerts")
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return yaml.safe_load(response.text) or {}

    # --- active alerts ---

    async def get_active_alerts(self) -> list[dict[str, Any]]:
        response = await self.request("GET", "/alertmanager/api/v2/alerts")
        response.raise_for_status()
        return response.json()

    # --- silences ---

    async def create_silence(self, silence: dict[str, Any]) -> str:
        response = await self.request(
            "POST", "/alertmanager/api/v2/silences", json=silence
        )
        response.raise_for_status()
        return response.json().get("silenceID", "")

    async def delete_silence(self, silence_id: str) -> None:
        response = await self.request(
            "DELETE", f"/alertmanager/api/v2/silence/{silence_id}"
        )
        if response.status_code != 404:
            response.raise_for_status()
