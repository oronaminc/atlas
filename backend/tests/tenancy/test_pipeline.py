"""Pipeline tenancy: org->tenant ingest attribution, NO cross-tenant
incident merge for the same host, tenant-scoped fanout + per-tenant config."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.models.alerting import AlertEvent, Incident
from app.models.delivery import Notification, NotificationSettings
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending
from app.providers.registry import get_provider
from app.services.correlation.config import get_config
from app.services.correlation.dedup import InMemoryDedupStore
from app.services.correlation.engine import CorrelationEngine, build_event
from app.services.correlation.strategy import AttributeTimeStrategy

NOW = datetime(2026, 6, 13, 2, 0, 0, tzinfo=UTC)

PAYLOAD = {
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "DiskFull", "severity": "critical", "host": "web-01"},
            "annotations": {},
            "startsAt": "2026-06-13T02:00:00Z",
        }
    ]
}


async def test_org_route_stamps_tenant(client, db, tenant_a):
    res = await client.post(
        "/api/v1/ingest/alertmanager/org-a",
        json=PAYLOAD,
        headers={"X-Atlas-Ingest-Key": "test-ingest-key"},
    )
    assert res.status_code == 202
    event = (await db.execute(select(AlertEvent))).scalars().one()
    assert event.tenant_id == tenant_a.id


async def test_unknown_or_inactive_org_404(client, db, tenant_a):
    res = await client.post(
        "/api/v1/ingest/alertmanager/org-nope",
        json=PAYLOAD,
        headers={"X-Atlas-Ingest-Key": "test-ingest-key"},
    )
    assert res.status_code == 404

    tenant_a.is_active = False
    await db.commit()
    from app.core.tenancy import invalidate_org_cache

    invalidate_org_cache()
    res = await client.post(
        "/api/v1/ingest/alertmanager/org-a",
        json=PAYLOAD,
        headers={"X-Atlas-Ingest-Key": "test-ingest-key"},
    )
    assert res.status_code == 404


async def test_ingest_key_accepted_as_bearer(client, db, tenant_a):
    """Mimir AM webhooks can only set Authorization (http_config)."""
    res = await client.post(
        "/api/v1/ingest/alertmanager/org-a",
        json=PAYLOAD,
        headers={"Authorization": "Bearer test-ingest-key"},
    )
    assert res.status_code == 202


async def test_same_host_two_tenants_no_merge(db, tenant_a, tenant_b):
    """THE collision bug: both subsidiaries run host=web-01 with the same
    alert labels -> identical fingerprint + group_key. Must yield two
    incidents, one per tenant, and dedup must not collapse across them."""
    engine = CorrelationEngine(
        dedup_store=InMemoryDedupStore(), strategies=[AttributeTimeStrategy()]
    )
    provider = get_provider("alertmanager")
    config = await get_config(db)

    [alert] = provider.parse(PAYLOAD)
    for tenant in (tenant_a, tenant_b):
        event = build_event(alert, received_at=NOW, tenant_id=tenant.id)
        db.add(event)
        await db.flush()
        await engine.correlate(db, event, alert, config, now=NOW)
    await db.commit()

    incidents = list((await db.execute(select(Incident))).scalars())
    assert len(incidents) == 2
    assert {i.tenant_id for i in incidents} == {tenant_a.id, tenant_b.id}
    assert all(i.group_key == "host=web-01" for i in incidents)
    # the second tenant's event survived as its own row (no dedup collapse)
    events = list((await db.execute(select(AlertEvent))).scalars())
    assert {e.tenant_id for e in events} == {tenant_a.id, tenant_b.id}


async def test_fanout_only_matches_own_tenant_routes(db, world_a, world_b, tenant_a, tenant_b):
    """A fresh un-notified incident in tenant A must create outbox rows ONLY
    for A's route/members even though B has an enabled route too."""
    from app.models.alerting import IncidentStatus

    incident = Incident(
        tenant_id=tenant_a.id,
        title="storm a",
        status=IncidentStatus.open,
        severity="critical",
        group_key="host=db-01",
        first_seen=NOW,
        last_seen=NOW,
        alert_count=1,
    )
    db.add(incident)
    # pre-existing seeded incidents shouldn't fan out in this test
    world_a["incident"].notified_at = NOW
    world_b["incident"].notified_at = NOW
    await db.commit()

    created = await fan_out_pending(db, now=NOW)
    await db.commit()
    assert created == 1  # only A's single member

    rows = list(
        (
            await db.execute(select(Notification).where(Notification.incident_id == incident.id))
        ).scalars()
    )
    assert len(rows) == 1
    assert rows[0].tenant_id == tenant_a.id
    assert rows[0].recipient_address == "chat-a"


async def test_per_tenant_settings_and_quota_isolation(db, tenant_a, tenant_b, world_a, world_b):
    """A's quota freeze must not stop B's sends, and each tenant's channel
    set comes from its own settings row (own bot token)."""
    db.add(
        NotificationSettings(
            tenant_id=tenant_a.id,
            telegram_bot_token=None,
            telegram_rate_per_second=25,
            quota_group_per_hour=0,  # A frozen
            quota_global_per_day=1000,
        )
    )
    db.add(
        NotificationSettings(
            tenant_id=tenant_b.id,
            telegram_bot_token=None,
            telegram_rate_per_second=25,
            quota_group_per_hour=100,
            quota_global_per_day=1000,
        )
    )
    await db.commit()

    sent_to: list[str] = []

    class FakeChannel:
        async def send(self, address: str, text: str) -> None:
            sent_to.append(address)

    sent = await deliver_once(
        db,
        worker_id="w",
        now=NOW,
        channels={"telegram": FakeChannel()},
    )
    await db.commit()
    # A's pending row deferred by quota 0; B's delivered
    assert sent == 1
    assert sent_to == ["chat-b"]
    a_row = world_a["notification"]
    await db.refresh(a_row)
    assert a_row.status == "pending" and a_row.retry_at is not None


async def test_per_tenant_channels_use_own_bot_token(db, tenant_a, tenant_b, world_a, world_b):
    """deliver_once builds channels from each row's tenant settings — B has
    a token (channel exists), A has none (channel not configured)."""
    from app.core.security import encrypt_secret

    db.add(
        NotificationSettings(
            tenant_id=tenant_b.id,
            telegram_bot_token=encrypt_secret("bot-token-b"),
            telegram_rate_per_second=25,
            quota_group_per_hour=100,
            quota_global_per_day=1000,
        )
    )
    await db.commit()

    sent = await deliver_once(db, worker_id="w", now=NOW)  # no channel override
    await db.commit()
    assert sent == 0  # B's telegram channel exists but send fails (no real API) or sends
    a_row, b_row = world_a["notification"], world_b["notification"]
    await db.refresh(a_row)
    await db.refresh(b_row)
    # A: no token -> channel not configured -> failed
    assert a_row.status == "failed" and "not configured" in (a_row.last_error or "")
    # B: token present -> channel built -> attempted (fails on network, not config)
    assert b_row.status == "failed" and "not configured" not in (b_row.last_error or "")
