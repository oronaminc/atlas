"""Stage 7 e2e: incident -> per-group channels -> delivery, end to end.

Each group owns its channel set (its own telegram bot+chats, emails, oncall
webhook). Fanout routes by l2 -> group(s) -> that group's channels, gated by the
incident's per-channel toggles. Sends are mocked here, but the path (fanout row
-> group_channel -> per-group secret -> channel.send) is real; a real dev send
is one config step away (a real bot_token + chat_id)."""

import pytest

from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending
from tests.notifications.helpers import (
    NOW,
    FakeChannel,
    seed_group,
    seed_group_channel,
    seed_incident,
    seed_route,
)

pytestmark = pytest.mark.asyncio


async def _drain(db, channels):
    """Run fanout then deliver everything; return the FakeChannels by name."""
    await fan_out_pending(db, now=NOW)
    await db.commit()
    # deliver in a loop until the queue is empty
    while True:
        res = await deliver_once(db, worker_id="w", now=NOW, channels=channels, limit=50)
        await db.commit()
        if res.claimed == 0:
            break


async def test_group_a_channels_with_toggles(db):
    # group A: telegram bot + 2 chats, 1 email, 1 oncall webhook
    group = await seed_group(db, "team-a", [])
    await seed_route(db, group)  # maps team-a -> L2TEST
    await seed_group_channel(db, group, "telegram", bot_token="botA", chat_id="chat-1")
    await seed_group_channel(db, group, "telegram", bot_token="botA", chat_id="chat-2")
    await seed_group_channel(db, group, "email", email="ops-a@example.com")
    await seed_group_channel(db, group, "oncall", webhook_url="https://oncall.a/hook")
    # incident toggles: telegram ON, email ON, oncall OFF
    await seed_incident(db, channels=["telegram", "email"])
    await db.commit()

    tg, em, oc = FakeChannel(), FakeChannel(), FakeChannel()
    await _drain(db, {"telegram": tg, "email": em, "oncall": oc})

    assert len(tg.sent) == 2  # both chats of group A's bot
    assert {addr for addr, _ in tg.sent} == {"chat-1", "chat-2"}
    assert len(em.sent) == 1 and em.sent[0][0] == "ops-a@example.com"
    assert len(oc.sent) == 0  # oncall toggle OFF


async def test_two_groups_same_l2_each_own_channels(db):
    a = await seed_group(db, "team-a", [])
    b = await seed_group(db, "team-b", [])
    await seed_route(db, a)  # both -> L2TEST
    await seed_route(db, b)
    await seed_group_channel(db, a, "telegram", bot_token="botA", chat_id="a-chat")
    await seed_group_channel(db, b, "telegram", bot_token="botB", chat_id="b-chat")
    await seed_incident(db, channels=["telegram"])
    await db.commit()

    tg = FakeChannel()
    await _drain(db, {"telegram": tg})
    # each group's own destination fired (its own bot resolves at send via group_channel_id)
    assert {addr for addr, _ in tg.sent} == {"a-chat", "b-chat"}


async def test_no_recipients_no_crash(db):
    # l2 mapped to a group that has NO channels -> decision I (warn+metric, no rows)
    group = await seed_group(db, "team-empty", [])
    await seed_route(db, group)
    await seed_incident(db, channels=["telegram", "email", "oncall"])
    await db.commit()
    n = await fan_out_pending(db, now=NOW)
    await db.commit()
    assert n == 0  # nothing created, no crash


async def test_dedup_no_duplicate_on_reprocess(db):
    group = await seed_group(db, "team-a", [])
    await seed_route(db, group)
    await seed_group_channel(db, group, "telegram", bot_token="botA", chat_id="chat-1")
    inc = await seed_incident(db, channels=["telegram"])
    await db.commit()
    await fan_out_pending(db, now=NOW)
    await db.commit()
    # clear the notified_at CAS guard to force a re-fan-out attempt
    inc.notified_at = None
    await db.commit()
    await fan_out_pending(db, now=NOW)
    await db.commit()
    from sqlalchemy import func, select

    from app.models.delivery import Notification

    total = (await db.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert total == 1  # dedup on (incident, channel, recipient_address)


async def test_oncall_only_when_toggled(db):
    group = await seed_group(db, "team-a", [])
    await seed_route(db, group)
    await seed_group_channel(db, group, "oncall", webhook_url="https://oncall.a/hook")
    await seed_group_channel(db, group, "telegram", bot_token="botA", chat_id="c1")
    await seed_incident(db, channels=["oncall"])  # only oncall on
    await db.commit()
    tg, oc = FakeChannel(), FakeChannel()
    await _drain(db, {"telegram": tg, "oncall": oc})
    assert len(oc.sent) == 1 and len(tg.sent) == 0
