"""Channel #1: Telegram Bot API sendMessage."""

import httpx

from app.notifications.channels.base import ChannelSendError


class TelegramChannel:
    name = "telegram"

    def __init__(
        self,
        token: str,
        api_base: str = "https://api.telegram.org",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    async def send(self, address: str, text: str) -> None:
        url = f"{self._api_base}/bot{self._token}/sendMessage"
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.post(url, json={"chat_id": address, "text": text})
            if response.status_code >= 400:
                raise ChannelSendError(
                    f"telegram api {response.status_code}: {response.text[:200]}"
                )
        except ChannelSendError:
            raise
        except Exception as exc:
            raise ChannelSendError(f"telegram send failed: {exc}") from exc
