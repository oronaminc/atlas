"""Two-world l2 fixtures (replaces the removed tenancy conftest).

Multi-tenancy is gone; row visibility is now solely the l2 choke point
(app/core/visibility.py): non-admins see Alert/Incident whose
cmdb_service_l2_code is in their group->group_service_codes mapping. The two
"worlds" are reframed to two l2 codes: world A stamps L2A, world B stamps L2B.

- a_admin   = admin (scope None, sees everything)
- a_viewer / a_editor = users mapped to L2A
- b_viewer  = user mapped to L2B

Each world seeds one incident + alert event + group + membership + a pending
notification under its l2 (same group_key on purpose so the only thing that
isolates them is the l2 code).
"""

from datetime import UTC, datetime

import pytest_asyncio

from app.models import Group, UserGroup
from app.models.alerting import AlertEvent, Incident, IncidentStatus
from app.models.delivery import Notification
from app.models.group import GroupServiceCode
from app.models.user import GlobalRole, User
from tests.conftest import make_user

NOW = datetime(2026, 6, 13, 1, 0, 0, tzinfo=UTC)

L2A = "L2A"
L2B = "L2B"


async def seed_l2_world(db, l2: str, tag: str) -> dict:
    """One incident + alert event + group/membership/notification for an l2."""
    incident = Incident(
        title=f"HighCPU {tag}",
        status=IncidentStatus.open,
        severity="critical",
        group_key="host=web-01",  # SAME host key on purpose (collision test)
        first_seen=NOW,
        last_seen=NOW,
        alert_count=1,
        cmdb_service_l2_code=l2,
    )
    db.add(incident)
    await db.flush()
    event = AlertEvent(
        fingerprint=f"fp-{tag}",
        source="alertmanager",
        name=f"HighCPU-{tag}",
        severity="critical",
        status="firing",
        labels={"host": "web-01"},
        annotations={},
        starts_at=NOW,
        received_at=NOW,
        incident_id=incident.id,
        cmdb_service_l2_code=l2,
    )
    db.add(event)
    group = Group(name=f"oncall-{tag}")
    db.add(group)
    await db.flush()
    db.add(GroupServiceCode(group_id=group.id, cmdb_service_l2_code=l2))
    member = await make_user(db, f"member-{tag}@example.com", GlobalRole.viewer)
    member.telegram_chat_id = f"chat-{tag}"
    db.add(UserGroup(user_id=member.id, group_id=group.id))
    notification = Notification(
        incident_id=incident.id,
        channel="telegram",
        recipient_user_id=member.id,
        recipient_address=f"chat-{tag}",
        group_id=group.id,
        status="pending",
    )
    db.add(notification)
    await db.commit()
    return {
        "incident": incident,
        "event": event,
        "group": group,
        "notification": notification,
        "member": member,
        "l2": l2,
    }


async def l2_user(db, l2: str, role: GlobalRole, tag: str) -> User:
    """A user mapped (via a fresh group) to the given l2 unless admin."""
    user = await make_user(db, f"{role.value}-{tag}@example.com", role)
    if role != GlobalRole.admin:
        group = Group(name=f"grp-{role.value}-{tag}")
        db.add(group)
        await db.flush()
        db.add(UserGroup(user_id=user.id, group_id=group.id))
        db.add(GroupServiceCode(group_id=group.id, cmdb_service_l2_code=l2))
        await db.commit()
        await db.refresh(user)
    return user


# Compatibility fixtures named after the old two-tenant world. They now carry
# only l2 semantics (no Tenant rows). `tenant_a`/`tenant_b` expose a `.id` of
# None and a `.l2` attribute for tests that still reference them.


class _World:
    """Lightweight stand-in for the removed Tenant fixture: carries the l2 code
    so reframed tests can read `.l2`. `.id` is None (no tenant rows anymore)."""

    def __init__(self, l2: str):
        self.l2 = l2
        self.id = None
        self.slug = l2.lower()


@pytest_asyncio.fixture
async def tenant_a():
    return _World(L2A)


@pytest_asyncio.fixture
async def tenant_b():
    return _World(L2B)


@pytest_asyncio.fixture
async def world_a(db):
    return await seed_l2_world(db, L2A, "a")


@pytest_asyncio.fixture
async def world_b(db):
    return await seed_l2_world(db, L2B, "b")


@pytest_asyncio.fixture
async def a_admin(db):
    return await l2_user(db, L2A, GlobalRole.admin, "a")


@pytest_asyncio.fixture
async def a_editor(db):
    return await l2_user(db, L2A, GlobalRole.editor, "a")


@pytest_asyncio.fixture
async def a_viewer(db):
    return await l2_user(db, L2A, GlobalRole.viewer, "a")


@pytest_asyncio.fixture
async def b_viewer(db):
    return await l2_user(db, L2B, GlobalRole.viewer, "b")
