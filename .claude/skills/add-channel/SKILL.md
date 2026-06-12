---
name: add-channel
description: Add a new notification delivery channel (Slack, SMS, webhook, ...). Use when asked to deliver incident notifications to a new target.
---

# Add a notification channel

Delivery worker/outbox are channel-agnostic. A new channel is one module +
one registry line. Do NOT touch outbox/delivery/fanout.

## Steps (TDD: test first)

1. Test in `backend/tests/notifications/test_channels.py`: mock the external
   API (httpx `MockTransport` for HTTP, monkeypatch for SDK/SMTP-style),
   assert payload shape; failure must raise `ChannelSendError` (that is what
   schedules the retry/backoff).
2. `backend/app/notifications/channels/<name>.py`:
   ```python
   class SlackChannel:
       name = "slack"
       async def send(self, address: str, text: str) -> None: ...
   ```
   `address` is the per-recipient target (chat_id/email/webhook URL snapshot).
   First line of `text` is the title (email uses it as subject).
3. Wire config: secrets go in `notification_settings` (Fernet-encrypted like
   the telegram token) or env (like SMTP). Add to
   `channels/registry.py::build_channels` — only include the channel when its
   config exists.
4. Recipient address source: extend `fanout.build_targets` with the new
   channel→address mapping (e.g. user.slack_id needs a users column + 000X
   migration + admin users PATCH field). Update fanout tests.
5. If routes should offer it in the UI: add to the channel toggles in
   `frontend/src/features/notifications/notification-admin.tsx`.
6. Run backend-check; verify quota/throttle/retry behavior is inherited for
   free via `tests/notifications/test_delivery.py` patterns.

## Gotchas

- Wrap ALL failures in `ChannelSendError` — unwrapped exceptions still mark
  the row failed, but lose the clean error message.
- Respect air-gap: HTTP clients must accept an injectable transport for tests;
  no SDKs that phone home or fetch resources at import time.
