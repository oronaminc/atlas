"""Channel #2: Email via SMTP (credentials from env)."""

import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.notifications.channels.base import ChannelSendError


def smtp_send(to: str, subject: str, body: str) -> None:
    """Blocking SMTP delivery; module-level so tests can monkeypatch it."""
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(message)


class EmailChannel:
    name = "email"

    async def send(self, address: str, text: str) -> None:
        subject, _, body = text.partition("\n")
        try:
            await asyncio.to_thread(smtp_send, address, subject, body or subject)
        except Exception as exc:
            raise ChannelSendError(f"smtp send failed: {exc}") from exc
