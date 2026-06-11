"""Channel boundary: each delivery target implements send(address, text).
New channel = new module + registry entry; engine/worker untouched."""

from typing import Protocol


class ChannelSendError(Exception):
    """Raised on any delivery failure; the outbox schedules a retry."""


class NotificationChannel(Protocol):
    name: str

    async def send(self, address: str, text: str) -> None: ...
