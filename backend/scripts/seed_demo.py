"""Seed demo data for the ops dashboard: incidents with alerts/timeline,
notification rows in every status, and alert events spread over 24h.

Usage:
    uv run python scripts/seed_demo.py
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.models import Group, User, UserGroup  # noqa: E402
from app.models.alerting import (
    AlertEvent,
    Incident,
    IncidentEvent,
    IncidentStatus,
)  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.delivery import Notification  # noqa: E402

HOSTS = ["web-01", "web-02", "db-01", "cache-01"]
SEVERITIES = ["critical", "warning", "info"]


async def main() -> None:
    now = utcnow()
    async with async_session_factory() as db:
        users = []
        for i, name in enumerate(["oncall-kim", "oncall-lee", "oncall-park"]):
            user = User(
                email=f"{name}@example.com",
                username=name,
                hashed_password=hash_password("password123"),
                telegram_chat_id=str(1000 + i),
            )
            db.add(user)
            users.append(user)
        await db.flush()
        group = Group(name="oncall-demo")
        db.add(group)
        await db.flush()
        for user in users:
            db.add(UserGroup(user_id=user.id, group_id=group.id))

        incidents = []
        specs = [
            ("HighCPU on web-01", "host=web-01", "critical", IncidentStatus.open, 5),
            ("DiskFull on db-01", "host=db-01", "critical", IncidentStatus.open, 3),
            (
                "HighMemory on web-02",
                "host=web-02",
                "warning",
                IncidentStatus.acknowledged,
                2,
            ),
            ("SlowQueries on db-01", "host=db-01", "warning", IncidentStatus.open, 4),
            (
                "CacheEvictions on cache-01",
                "host=cache-01",
                "info",
                IncidentStatus.resolved,
                1,
            ),
            (
                "HighLatency on web-01",
                "host=web-01",
                "warning",
                IncidentStatus.resolved,
                2,
            ),
        ]
        for i, (title, group_key, severity, status, n_alerts) in enumerate(specs):
            first = now - timedelta(hours=20 - i * 3)
            incident = Incident(
                title=title,
                status=status,
                severity=severity,
                group_key=group_key,
                first_seen=first,
                last_seen=first + timedelta(minutes=30 * n_alerts),
                alert_count=n_alerts,
                notified_at=now,
            )
            db.add(incident)
            await db.flush()
            incidents.append(incident)
            db.add(IncidentEvent(incident_id=incident.id, kind="created", payload={}))
            for j in range(n_alerts):
                received = first + timedelta(minutes=30 * j)
                event = AlertEvent(
                    fingerprint=f"demo-{i}-{j}",
                    source="alertmanager" if j % 2 == 0 else "datadog",
                    name=f"{title.split(' on ')[0]}-{j}",
                    severity=severity,
                    status="firing",
                    labels={"host": group_key.split("=", 1)[1]},
                    annotations={"summary": title},
                    starts_at=received,
                    received_at=received,
                    incident_id=incident.id,
                    dedup_count=j + 1,
                )
                db.add(event)
                await db.flush()
                db.add(
                    IncidentEvent(
                        incident_id=incident.id,
                        kind="alert_attached",
                        payload={"alert_event_id": str(event.id), "name": event.name},
                    )
                )

        # notifications in every status against the first incident
        for user, (status, error) in zip(
            users,
            [
                ("sent", None),
                ("failed", "telegram api 429: Too Many Requests"),
                ("pending", None),
            ],
            strict=False,
        ):
            db.add(
                Notification(
                    incident_id=incidents[0].id,
                    channel="telegram",
                    recipient_user_id=user.id,
                    recipient_address=user.telegram_chat_id or "",
                    group_id=group.id,
                    status=status,
                    attempts=1 if status == "failed" else 0,
                    sent_at=now - timedelta(minutes=5) if status == "sent" else None,
                    retry_at=(
                        now + timedelta(minutes=10) if status == "failed" else None
                    ),
                    last_error=error,
                )
            )
        db.add(
            Notification(
                incident_id=incidents[1].id,
                channel="email",
                recipient_user_id=users[0].id,
                recipient_address=users[0].email,
                group_id=group.id,
                status="dead",
                attempts=5,
                last_error="smtp send failed: connection refused",
            )
        )
        await db.commit()
    print(
        f"seeded: {len(specs)} incidents, {sum(s[4] for s in specs)} alerts, 4 notifications"
    )


if __name__ == "__main__":
    asyncio.run(main())
