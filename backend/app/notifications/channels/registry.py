"""Channel construction. Every channel is PER-GROUP: built from a GroupChannel
row's own secrets (telegram bot token / oncall webhook), not a global config.
Email uses env SMTP. New channel = new module + a branch here."""

from app.core.security import decrypt_secret
from app.models.delivery import GroupChannel
from app.notifications.channels.base import NotificationChannel
from app.notifications.channels.email import EmailChannel
from app.notifications.channels.oncall import OncallChannel
from app.notifications.channels.telegram import TelegramChannel


def channel_for(gc: GroupChannel) -> NotificationChannel | None:
    """Build the channel instance for one group-channel config, decrypting its
    own secrets. Returns None if the row is incomplete (skip — no recipients)."""
    if gc.channel == "email":
        return EmailChannel()
    if gc.channel == "telegram":
        if not gc.bot_token or not gc.chat_id:
            return None
        return TelegramChannel(token=decrypt_secret(gc.bot_token))
    if gc.channel == "oncall":
        if not gc.webhook_url:
            return None
        return OncallChannel(
            webhook_url=decrypt_secret(gc.webhook_url),
            token=decrypt_secret(gc.oncall_token) if gc.oncall_token else None,
        )
    return None
