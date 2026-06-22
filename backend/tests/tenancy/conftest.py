"""Two-tenant world: tenants A/B with mapped Mimir orgs, per-tenant users
in every role, an HQ admin/viewer (tenant_id NULL), and per-tenant data
(incident + alert + notification route/row + group)."""

from datetime import UTC, datetime

import pytest_asyncio

from app.core.tenancy import invalidate_org_cache
from app.models import Group, UserGroup
from app.models.alerting import AlertEvent, Incident, IncidentStatus
from app.models.delivery import Notification, NotificationRoute
from app.models.tenant import MimirOrgMap, Tenant
from app.models.user import GlobalRole
from tests.conftest import make_user

NOW = datetime(2026, 6, 13, 1, 0, 0, tzinfo=UTC)


async def make_tenant(db, slug: str, org: str) -> Tenant:
    tenant = Tenant(slug=slug, name=slug.upper(), is_active=True)
    db.add(tenant)
    await db.flush()
    db.add(MimirOrgMap(mimir_org=org, tenant_id=tenant.id))
    await db.commit()
    await db.refresh(tenant)
    invalidate_org_cache()
    return tenant


async def seed_tenant_world(db, tenant: Tenant, tag: str) -> dict:
    """One incident + alert event + group/route/notification for a tenant."""
    incident = Incident(
        tenant_id=tenant.id,
        title=f"HighCPU {tag}",
        status=IncidentStatus.open,
        severity="critical",
        group_key="host=web-01",  # SAME host key on purpose (collision test)
        first_seen=NOW,
        last_seen=NOW,
        alert_count=1,
        cmdb_service_l2_code="L2TEST",
    )
    db.add(incident)
    await db.flush()
    event = AlertEvent(
        tenant_id=tenant.id,
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
        cmdb_service_l2_code="L2TEST",
    )
    db.add(event)
    group = Group(tenant_id=tenant.id, name=f"oncall-{tag}")
    db.add(group)
    await db.flush()
    member = await make_user(db, f"member-{tag}@example.com", GlobalRole.viewer)
    member.tenant_id = tenant.id
    member.telegram_chat_id = f"chat-{tag}"
    db.add(UserGroup(user_id=member.id, group_id=group.id))
    route = NotificationRoute(
        tenant_id=tenant.id,
        group_id=group.id,
        min_severity="info",
        channels=["telegram"],
        enabled=True,
    )
    db.add(route)
    notification = Notification(
        tenant_id=tenant.id,
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
        "route": route,
        "notification": notification,
        "member": member,
    }


@pytest_asyncio.fixture
async def tenant_a(db):
    return await make_tenant(db, "sub-a", "org-a")


@pytest_asyncio.fixture
async def tenant_b(db):
    return await make_tenant(db, "sub-b", "org-b")


@pytest_asyncio.fixture
async def world_a(db, tenant_a):
    return await seed_tenant_world(db, tenant_a, "a")


@pytest_asyncio.fixture
async def world_b(db, tenant_b):
    return await seed_tenant_world(db, tenant_b, "b")


async def tenant_user(db, tenant: Tenant, role: GlobalRole, tag: str):
    user = await make_user(db, f"{role.value}-{tag}@example.com", role)
    user.tenant_id = tenant.id
    await db.commit()
    await db.refresh(user)
    # IMP visibility: non-admins need an l2 mapping to see the L2TEST-stamped
    # seed data (tenant isolation is still enforced by tenant_id underneath).
    if role != GlobalRole.admin:
        from tests.conftest import _grant_l2

        await _grant_l2(db, user)
    return user


@pytest_asyncio.fixture
async def a_admin(db, tenant_a):
    return await tenant_user(db, tenant_a, GlobalRole.admin, "a")


@pytest_asyncio.fixture
async def a_editor(db, tenant_a):
    return await tenant_user(db, tenant_a, GlobalRole.editor, "a")


@pytest_asyncio.fixture
async def a_viewer(db, tenant_a):
    return await tenant_user(db, tenant_a, GlobalRole.viewer, "a")


@pytest_asyncio.fixture
async def b_viewer(db, tenant_b):
    return await tenant_user(db, tenant_b, GlobalRole.viewer, "b")
