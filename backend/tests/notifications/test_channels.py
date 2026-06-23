"""Channel boundary: Telegram (mocked Bot API), Email (mocked SMTP), registry."""

import httpx
import pytest

from app.notifications.channels.base import ChannelSendError
from app.notifications.channels.email import EmailChannel
from app.notifications.channels.telegram import TelegramChannel


async def test_telegram_posts_to_bot_api():
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    channel = TelegramChannel(token="TESTTOKEN", transport=httpx.MockTransport(handler))
    await channel.send("12345", "incident: HighCPU")

    request = captured[0]
    assert "botTESTTOKEN/sendMessage" in str(request.url)
    import json

    body = json.loads(request.content)
    assert body["chat_id"] == "12345"
    assert "HighCPU" in body["text"]


async def test_telegram_api_error_raises_channel_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"ok": False, "description": "Too Many Requests"})

    channel = TelegramChannel(token="T", transport=httpx.MockTransport(handler))
    with pytest.raises(ChannelSendError):
        await channel.send("12345", "x")


async def test_email_sends_via_smtp(monkeypatch):
    sent: list[tuple[str, str, str]] = []

    def fake_smtp_send(to: str, subject: str, body: str) -> None:
        sent.append((to, subject, body))

    monkeypatch.setattr("app.notifications.channels.email.smtp_send", fake_smtp_send)
    await EmailChannel().send("ops@example.com", "[Atlas] HighCPU on web-01\ncritical alert")

    to, subject, body = sent[0]
    assert to == "ops@example.com"
    assert "HighCPU" in subject  # first line becomes the subject
    assert "critical" in body


async def test_email_smtp_failure_raises_channel_error(monkeypatch):
    def boom(to, subject, body):
        raise ConnectionError("smtp down")

    monkeypatch.setattr("app.notifications.channels.email.smtp_send", boom)
    with pytest.raises(ChannelSendError):
        await EmailChannel().send("ops@example.com", "x")


def test_registry_channel_for_per_group():
    from app.core.security import encrypt_secret
    from app.models.delivery import GroupChannel
    from app.notifications.channels.registry import channel_for

    email = channel_for(GroupChannel(channel="email", email="a@x.io"))
    assert email is not None and email.name == "email"

    tg = channel_for(
        GroupChannel(channel="telegram", bot_token=encrypt_secret("REAL"), chat_id="c1")
    )
    assert tg is not None and tg.name == "telegram"
    # incomplete telegram (no token) -> None (skipped, no recipients)
    assert channel_for(GroupChannel(channel="telegram", chat_id="c1")) is None

    oncall = channel_for(GroupChannel(channel="oncall", webhook_url=encrypt_secret("https://h")))
    assert oncall is not None and oncall.name == "oncall"
