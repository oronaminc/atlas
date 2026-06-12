"""Mimir Ruler API client.

The ruler exposes the Prometheus rule-group config API:
  GET    /<namespace>                 -> rule groups in namespace (YAML)
  POST   /<namespace>                 -> create/update one rule group (YAML body)
  DELETE /<namespace>/<group_name>    -> delete a rule group

`settings.MIMIR_RULER_URL` already points at the rules prefix, e.g.
http://mimir:8080/prometheus/config/v1/rules
"""

from typing import Any

import yaml

from app.core.config import settings
from app.integrations.base import BaseIntegrationClient


class MimirRulerClient(BaseIntegrationClient):
    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url or settings.MIMIR_RULER_URL)

    async def set_rule_group(
        self, namespace: str, group_payload: dict[str, Any]
    ) -> None:
        """PUT(sync) one Prometheus rule group into the given namespace."""
        body = yaml.safe_dump(group_payload, sort_keys=False)
        response = await self.request(
            "POST",
            f"/{namespace}",
            content=body,
            headers={"Content-Type": "application/yaml"},
        )
        response.raise_for_status()

    async def delete_rule_group(self, namespace: str, group_name: str) -> None:
        response = await self.request("DELETE", f"/{namespace}/{group_name}")
        if response.status_code != 404:
            response.raise_for_status()

    async def get_namespace(self, namespace: str) -> dict[str, Any]:
        response = await self.request("GET", f"/{namespace}")
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return yaml.safe_load(response.text) or {}


class MimirQueryClient(BaseIntegrationClient):
    """Prometheus-compatible query API (instant queries for rule previews)."""

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url or settings.MIMIR_QUERY_URL)

    async def instant_query(self, expr: str) -> dict[str, Any]:
        response = await self.request("GET", "/api/v1/query", params={"query": expr})
        response.raise_for_status()
        return response.json()
