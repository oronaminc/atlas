"""Channel #3: OnCall — a team webhook (IMP §7/J), not per-user. Posts the
incident text to the configured oncall_webhook_url with an optional bearer
token. One outbox row per incident; `address` carries the incident's topology
scope (l2 code) for the receiving system's context."""

import httpx

from app.notifications.channels.base import ChannelSendError


class OncallChannel:
    name = "oncall"

    def __init__(
        self,
        webhook_url: str,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._url = webhook_url
        self._token = token
        self._transport = transport
        self._timeout = timeout

    async def send(self, address: str, text: str) -> None:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.post(
                    self._url, json={"scope": address, "text": text}, headers=headers
                )
            if response.status_code >= 400:
                raise ChannelSendError(
                    f"oncall webhook {response.status_code}: {response.text[:200]}"
                )
        except ChannelSendError:
            raise
        except Exception as exc:
            raise ChannelSendError(f"oncall send failed: {exc}") from exc
