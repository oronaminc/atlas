"""OpenAI-compatible chat client (vLLM / Ollama / internal gateway / OpenAI).

Deliberately NOT BaseIntegrationClient — that injects X-Scope-OrgID (a Mimir
header, wrong for an LLM). Own httpx client: POST {base_url}/v1/chat/completions
with `Authorization: Bearer {api_key}`. Tests inject a mock transport so no
real network call ever happens. Air-gap: base_url is whatever the service
configured; nothing is hardcoded to openai.com.
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 0.5


class LLMError(Exception):
    pass


class LLMTimeout(LLMError):
    pass


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._transport = transport

    async def complete(self, system: str, user: str, *, max_tokens: int = 512) -> tuple[str, int]:
        """Returns (content, total_tokens). Retries transient errors; raises
        LLMError/LLMTimeout on give-up (caller marks the job failed)."""
        url = f"{self._base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(
                    transport=self._transport, timeout=self._timeout
                ) as client:
                    resp = await client.post(url, json=body, headers=headers)
                if resp.status_code >= 500:
                    last_exc = LLMError(f"LLM server error {resp.status_code}")
                elif resp.status_code >= 400:
                    raise LLMError(f"LLM client error {resp.status_code}: {resp.text[:200]}")
                else:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    tokens = (data.get("usage") or {}).get("total_tokens", 0)
                    return content, tokens
            except httpx.TimeoutException as exc:
                last_exc = LLMTimeout(f"LLM timeout: {exc}")
            except (httpx.TransportError, KeyError, IndexError, ValueError) as exc:
                last_exc = LLMError(f"LLM call failed: {exc}")
            except LLMError:
                raise  # 4xx: don't retry
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF_BASE_SECONDS * (2**attempt))
        assert last_exc is not None
        raise last_exc
