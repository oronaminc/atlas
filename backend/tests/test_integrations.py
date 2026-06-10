import httpx
import pytest
import yaml

from app.core.config import settings
from app.integrations.base import BaseIntegrationClient, make_client


def test_make_client_injects_tenant_header():
    client = make_client("http://mimir:8080")
    assert client.headers["X-Scope-OrgID"] == settings.MIMIR_TENANT_ID
    assert settings.MIMIR_TENANT_ID == "system"


async def test_request_sends_tenant_header_once():
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    client = BaseIntegrationClient("http://mimir:8080")
    client._client._transport = httpx.MockTransport(handler)

    response = await client.request("GET", "/x")
    assert response.status_code == 200
    assert captured[0].headers["x-scope-orgid"] == "system"
    await client.aclose()


async def test_retry_with_backoff_on_5xx(monkeypatch):
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200)

    async def no_sleep(_):
        pass

    monkeypatch.setattr("app.integrations.base.asyncio.sleep", no_sleep)

    client = BaseIntegrationClient("http://mimir:8080")
    client._client._transport = httpx.MockTransport(handler)
    response = await client.request("GET", "/x")
    assert response.status_code == 200
    assert calls["n"] == 3
    await client.aclose()


async def test_retry_exhaustion_raises(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async def no_sleep(_):
        pass

    monkeypatch.setattr("app.integrations.base.asyncio.sleep", no_sleep)

    client = BaseIntegrationClient("http://mimir:8080")
    client._client._transport = httpx.MockTransport(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await client.request("GET", "/x")
    await client.aclose()


async def test_ruler_posts_yaml_rule_group():
    from app.integrations.mimir_ruler import MimirRulerClient

    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(202)

    ruler = MimirRulerClient("http://mimir:8080/prometheus/config/v1/rules")
    ruler._client._transport = httpx.MockTransport(handler)

    await ruler.set_rule_group(
        "atlas", {"name": "g", "interval": "1m", "rules": [{"alert": "A", "expr": "up == 0"}]}
    )
    request = captured[0]
    assert request.headers["x-scope-orgid"] == "system"
    assert request.headers["content-type"] == "application/yaml"
    body = yaml.safe_load(request.content)
    assert body["name"] == "g"
    assert body["rules"][0]["alert"] == "A"
    await ruler.aclose()
