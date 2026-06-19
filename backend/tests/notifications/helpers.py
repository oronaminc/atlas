"""Shared fixtures/helpers for notification tests."""

from datetime import UTC, datetime

from app.core.security import hash_password
from app.models import Group, User, UserGroup
from app.models.alerting import Incident, IncidentStatus
from app.models.delivery import NotificationRoute
from app.models.user import GlobalRole

NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)


async def seed_user(db, email: str, chat_id: str | None = None, role=GlobalRole.viewer) -> User:
    user = User(
        email=email,
        username=email.split("@")[0],
        hashed_password=hash_password("password123"),
        role=role,
        telegram_chat_id=chat_id,
    )
    db.add(user)
    await db.flush()
    return user


async def seed_group(db, name: str, members: list[User]) -> Group:
    group = Group(name=name)
    db.add(group)
    await db.flush()
    for member in members:
        db.add(UserGroup(user_id=member.id, group_id=group.id))
    await db.flush()
    return group


async def seed_route(
    db,
    group,
    min_severity: str = "warning",
    channels: list[str] | None = None,
    enabled: bool = True,
) -> NotificationRoute:
    route = NotificationRoute(
        group_id=group.id,
        min_severity=min_severity,
        channels=channels or ["telegram"],
        enabled=enabled,
    )
    db.add(route)
    await db.flush()
    return route


async def seed_incident(
    db, severity: str = "critical", title: str = "HighCPU on web-01"
) -> Incident:
    incident = Incident(
        title=title,
        status=IncidentStatus.open,
        severity=severity,
        group_key="host=web-01",
        first_seen=NOW,
        last_seen=NOW,
        alert_count=1,
    )
    db.add(incident)
    await db.flush()
    return incident


async def seed_incident_with_events(
    db, pairs: list[tuple[str | None, str]], *, severity: str = "critical", tenant_id=None
) -> Incident:
    """Incident carrying alert_events with given (cmdb_ci, alertname) pairs —
    for mute/threshold tests. cmdb_ci=None → label omitted."""
    from app.models.alerting import AlertEvent

    incident = Incident(
        title="test incident",
        status=IncidentStatus.open,
        severity=severity,
        group_key="host=test",
        first_seen=NOW,
        last_seen=NOW,
        alert_count=len(pairs),
        tenant_id=tenant_id,
    )
    db.add(incident)
    await db.flush()
    for i, (cmdb, name) in enumerate(pairs):
        db.add(
            AlertEvent(
                fingerprint=f"fp-{i}-{name}",
                source="alertmanager",
                name=name,
                severity=severity,
                status="firing",
                labels=({"cmdb_ci": cmdb} if cmdb else {}),
                annotations={},
                starts_at=NOW,
                received_at=NOW,
                incident_id=incident.id,
                tenant_id=tenant_id,
            )
        )
    await db.flush()
    return incident


class FakeChannel:
    """Records sends; can be told to fail."""

    def __init__(self, fail_times: int = 0):
        self.sent: list[tuple[str, str]] = []  # (address, text)
        self.fail_times = fail_times

    async def send(self, address: str, text: str) -> None:
        from app.notifications.channels.base import ChannelSendError

        if self.fail_times > 0:
            self.fail_times -= 1
            raise ChannelSendError("simulated failure")
        self.sent.append((address, text))


class FakeThrottle:
    def __init__(self):
        self.acquired: list[str] = []

    async def acquire(self, address: str) -> None:
        self.acquired.append(address)
