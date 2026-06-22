from app.core.security import decrypt_secret
from app.models.delivery import NotificationSettings
from app.notifications.channels.base import NotificationChannel
from app.notifications.channels.email import EmailChannel
from app.notifications.channels.oncall import OncallChannel
from app.notifications.channels.telegram import TelegramChannel


def build_channels(
    settings_row: NotificationSettings,
) -> dict[str, NotificationChannel]:
    """Channels available given current admin settings. Telegram appears once a
    bot token is set; OnCall once a webhook URL is set."""
    channels: dict[str, NotificationChannel] = {"email": EmailChannel()}
    if settings_row.telegram_bot_token:
        channels["telegram"] = TelegramChannel(
            token=decrypt_secret(settings_row.telegram_bot_token)
        )
    if settings_row.oncall_webhook_url:
        channels["oncall"] = OncallChannel(
            webhook_url=settings_row.oncall_webhook_url,
            token=decrypt_secret(settings_row.oncall_token) if settings_row.oncall_token else None,
        )
    return channels
