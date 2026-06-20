"""Atlas DEMO / UI-stress seed — realistic volume for manually exercising the UI.

WHAT IT CREATES (all tagged 'demo', tenant_id=NULL so HQ sees it):
  - 6 server groups            demo-web-tier / demo-api-tier / demo-db-tier /
                               demo-cache-tier / demo-batch-tier / demo-infra-tier
  - 50 servers                 demo-<tier>-NN.sktelecom.com, cmdb_ci DEMO-SVC1000NN,
                               with cmdb_* labels INCLUDING ip (cmdb_ip + instance)
  - 27 incidents               incl. one 20-alert incident, one 18-label alert,
                               one rich nested-JSON-timeline incident; varied
                               severity/status across hosts and the last 24h
  - rule catalog               10 Demo* alertnames (half configured, half pass-through)
  - 7 threshold overrides      server + group tiers (server targets = real cmdb_ci)
  - 4 notification mutes        server / group / all + alertname wildcards

EVERYTHING is prefixed so it is greppable and safe to remove:
  cmdb_ci  -> DEMO-SVC...      group name -> demo-...      hostname -> demo-...
  alertname -> Demo...         alert_events.fingerprint -> demo-...
  incident group_key -> host=demo-...

RUN (idempotent — clears prior demo data first, so re-running never duplicates):
  uv run python scripts/seed_ui_stress.py            # clear demo + reseed
  uv run python scripts/seed_ui_stress.py --clear    # remove demo data only

NEVER run against prod. This writes fabricated incidents/servers; it only ever
touches demo-prefixed rows, but it is a DEMO tool. See docs/demo-seed.md.
"""

import argparse
import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.models.alerting import AlertEvent, Incident, IncidentEvent, IncidentStatus  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.delivery import NotificationMute  # noqa: E402
from app.models.server import Server, ServerGroup  # noqa: E402
from app.models.threshold import RuleCatalog, ThresholdOverride  # noqa: E402

# --- demo markers (every selector below keys off these) ---
CMDB = "DEMO-SVC"  # cmdb_ci prefix
GROUP = "demo-"  # server-group name + hostname prefix
FP = "demo-"  # alert_events.fingerprint prefix
GK = "host=demo-"  # incident group_key prefix
ALERT = "Demo"  # alertname prefix

GROUPS = [
    ("demo-web-tier", "Public web frontends"),
    ("demo-api-tier", "Internal API services"),
    ("demo-db-tier", "PostgreSQL / MySQL clusters"),
    ("demo-cache-tier", "Redis / Memcached"),
    ("demo-batch-tier", "Nightly batch & ETL"),
    ("demo-infra-tier", "Networking & shared infra"),
]
ENVS = ["prod", "staging", "dev"]
OWNERS = ["sre-platform", "team-payments", "team-search", "team-data", "team-infra"]
APPS = ["checkout", "search", "ledger", "ingest", "gateway", "scheduler"]
LOCATIONS = ["icn-dc1", "icn-dc2", "pnu-dc1"]
ALERTNAMES = [
    "DemoHighCPUUsage",
    "DemoHighMemoryUsage",
    "DemoDiskWillFillIn4Hours",
    "DemoHostOutOfMemory",
    "DemoHighDiskIO",
    "DemoPacketLoss",
    "DemoTargetDown",
    "DemoHighLatencyP99",
    "DemoTooManyConnections",
    "DemoCertExpiringSoon",
]


async def clear(db) -> dict[str, int]:
    """Remove ONLY demo-prefixed rows. Order respects FKs."""
    counts: dict[str, int] = {}
    demo_groups = select(ServerGroup.id).where(ServerGroup.name.like(f"{GROUP}%"))
    demo_incidents = select(Incident.id).where(Incident.group_key.like(f"{GK}%"))
    for label, stmt in [
        ("alert_events", delete(AlertEvent).where(AlertEvent.fingerprint.like(f"{FP}%"))),
        (
            "incident_events",
            delete(IncidentEvent).where(IncidentEvent.incident_id.in_(demo_incidents)),
        ),
        ("incidents", delete(Incident).where(Incident.group_key.like(f"{GK}%"))),
        (
            "mutes",
            delete(NotificationMute).where(
                NotificationMute.target_cmdb_ci.like(f"{CMDB}%")
                | NotificationMute.target_group_id.in_(demo_groups)
                | NotificationMute.alertname.like(f"{ALERT}%")
            ),
        ),
        (
            "threshold_overrides",
            delete(ThresholdOverride).where(
                ThresholdOverride.target_cmdb_ci.like(f"{CMDB}%")
                | ThresholdOverride.target_group_id.in_(demo_groups)
                | ThresholdOverride.alertname.like(f"{ALERT}%")
            ),
        ),
        ("rule_catalog", delete(RuleCatalog).where(RuleCatalog.alertname.like(f"{ALERT}%"))),
        ("servers", delete(Server).where(Server.cmdb_ci.like(f"{CMDB}%"))),
        ("server_groups", delete(ServerGroup).where(ServerGroup.name.like(f"{GROUP}%"))),
    ]:
        res = await db.execute(stmt.execution_options(synchronize_session=False))
        counts[label] = res.rowcount
    await db.commit()
    return counts


async def seed(db) -> dict[str, int]:
    now = utcnow()

    groups = [ServerGroup(name=n, description=d) for n, d in GROUPS]
    for g in groups:
        db.add(g)
    await db.flush()

    # 50 servers — cmdb_ci <-> hostname is a single deterministic mapping reused
    # everywhere below, so an override/mute target always matches its server.
    servers = []
    for i in range(1, 51):
        grp = groups[i % len(groups)]
        tier = grp.name.removeprefix(GROUP).removesuffix("-tier")
        host = f"{GROUP}{tier}-{i:02d}.sktelecom.com"
        cmdb = f"{CMDB}{100000 + i}"
        ip = f"10.{i % 6}.{i}.{(i * 7) % 250}"
        labels = {
            "cmdb_ci": cmdb,
            "cmdb_hostname": host,
            "cmdb_ip": ip,
            "instance": f"{ip}:9100",
            "cmdb_env": ENVS[i % len(ENVS)],
            "cmdb_owner": OWNERS[i % len(OWNERS)],
            "cmdb_service_l1": APPS[i % len(APPS)],
            "cmdb_location": LOCATIONS[i % len(LOCATIONS)],
            "cmdb_tier": tier,
            "cmdb_managed_by": "ansible",
            "cmdb_cost_center": f"CC-{4000 + (i % 12)}",
            "demo": "atlas-ui-stress",
        }
        s = Server(
            name=host,
            cmdb_ci=cmdb,
            labels=labels,
            description=f"{tier} node {i}",
            server_group_id=grp.id,
        )
        db.add(s)
        servers.append(s)
    await db.flush()

    incidents = []

    def new_incident(server, alertname, severity, status, n, hours_ago):
        first = now - timedelta(hours=hours_ago)
        inc = Incident(
            title=f"{alertname} on {server.name}",
            status=status,
            severity=severity,
            group_key=f"host={server.name}",
            first_seen=first,
            last_seen=first + timedelta(minutes=6 * max(n, 1)),
            alert_count=n,
            notified_at=now,
        )
        db.add(inc)
        incidents.append(inc)
        return inc, first

    def alert(inc, server, alertname, severity, j, first, *, labels=None):
        ip = server.labels["cmdb_ip"]
        ev = AlertEvent(
            fingerprint=f"{FP}{inc.group_key}-{alertname}-{j}",
            source="alertmanager",
            name=alertname,
            severity=severity,
            status="firing",
            labels=labels
            or {
                "host": server.name,
                "cmdb_ci": server.cmdb_ci,
                "instance": f"{ip}:9100",
                "cmdb_hostname": server.name,
                "job": "node",
            },
            annotations={"summary": f"{alertname} on {server.name}"},
            starts_at=first + timedelta(minutes=4 * j),
            received_at=first + timedelta(minutes=4 * j),
            incident_id=inc.id,
            dedup_count=j + 1,
        )
        db.add(ev)
        return ev

    # 1) BIG multi-alert incident (20 alerts) on a web server
    s = servers[1]
    inc, first = new_incident(s, "DemoHighCPUUsage", "critical", IncidentStatus.open, 20, 6)
    await db.flush()
    db.add(IncidentEvent(incident_id=inc.id, kind="created", payload={}))
    for j in range(20):
        ev = alert(inc, s, ALERTNAMES[j % len(ALERTNAMES)], "critical", j, first)
        await db.flush()
        db.add(
            IncidentEvent(
                incident_id=inc.id,
                kind="alert_attached",
                payload={"alert_event_id": str(ev.id), "name": ev.name},
            )
        )

    # 2) MANY-LABEL incident (one alert, ~18 labels incl. long values)
    s = servers[2]
    inc, first = new_incident(
        s, "DemoTooManyConnections", "warning", IncidentStatus.acknowledged, 1, 4
    )
    await db.flush()
    db.add(IncidentEvent(incident_id=inc.id, kind="created", payload={}))
    big = {
        "host": s.name,
        "cmdb_ci": s.cmdb_ci,
        "cmdb_hostname": s.name,
        "instance": f"{s.labels['cmdb_ip']}:9187",
        "cmdb_env": "prod",
        "cmdb_owner": "team-payments",
        "cmdb_service_l1": "ledger",
        "cmdb_location": "icn-dc1",
        "job": "postgres-exporter",
        "datname": "payments_prod",
        "namespace": "payments",
        "pod": "pg-primary-0",
        "container": "postgres",
        "severity": "warning",
        "team": "team-payments",
        "runbook": "https://wiki.sktelecom.com/runbooks/postgres/too-many-connections-detailed-guide",
        "prometheus": "monitoring/k8s-prometheus",
        "service": "postgres-primary-payments-prod-readreplica-failover-candidate",
    }
    ev = alert(inc, s, "DemoTooManyConnections", "warning", 0, first, labels=big)
    ev.annotations = {
        "summary": "connections 480/500",
        "description": "Connection pool near exhaustion on payments_prod; "
        "consider raising max_connections or investigating leaked sessions.",
    }
    await db.flush()
    db.add(
        IncidentEvent(
            incident_id=inc.id,
            kind="alert_attached",
            payload={"alert_event_id": str(ev.id), "name": ev.name},
        )
    )

    # 3) RICH nested-JSON timeline incident
    s = servers[5]
    inc, first = new_incident(
        s, "DemoDiskWillFillIn4Hours", "critical", IncidentStatus.suppressed, 3, 3
    )
    await db.flush()
    for kind, payload in [
        ("created", {}),
        ("alert_attached", {"alert_event_id": "demo", "name": "DemoDiskWillFillIn4Hours"}),
        (
            "status_changed",
            {
                "from": "open",
                "to": "acknowledged",
                "actor": "oncall-kim",
                "note": "investigating, looks like log rotation stalled",
            },
        ),
        (
            "comment",
            {
                "author": "oncall-lee",
                "text": "Cleared 40GB of old WALs; monitoring. "
                "Root cause likely the archiver falling behind after the 2am deploy.",
                "attachments": [{"type": "grafana", "url": "https://g/d/abc"}],
            },
        ),
        (
            "notification_muted",
            {
                "reason": "planned maintenance window",
                "muted_pairs": [{"cmdb_ci": s.cmdb_ci, "alertname": "DemoDiskWillFillIn4Hours"}],
            },
        ),
        ("status_changed", {"from": "acknowledged", "to": "suppressed", "actor": "oncall-kim"}),
        (
            "llm_analysis",
            {
                "root_cause": "WAL archiver backlog",
                "confidence": 0.82,
                "recommended_actions": ["scale archiver", "raise disk alert floor"],
                "model": "gpt-4o-mini",
                "tokens": {"prompt": 1820, "completion": 240},
            },
        ),
    ]:
        db.add(IncidentEvent(incident_id=inc.id, kind=kind, payload=payload))
    for j in range(3):
        alert(inc, s, "DemoDiskWillFillIn4Hours", "critical", j, first)

    # 4) Volume: 24 more incidents across distinct servers/severity/status/time
    statuses = [
        IncidentStatus.open,
        IncidentStatus.acknowledged,
        IncidentStatus.resolved,
        IncidentStatus.suppressed,
    ]
    sevs = ["critical", "warning", "info"]
    for i in range(24):
        s = servers[i]
        name = ALERTNAMES[i % len(ALERTNAMES)]
        n = (i % 4) + 1
        inc, first = new_incident(s, name, sevs[i % 3], statuses[i % 4], n, 23 - (i % 22))
        await db.flush()
        db.add(IncidentEvent(incident_id=inc.id, kind="created", payload={}))
        for j in range(n):
            ev = alert(inc, s, name, sevs[i % 3], j, first)
            await db.flush()
            db.add(
                IncidentEvent(
                    incident_id=inc.id,
                    kind="alert_attached",
                    payload={"alert_event_id": str(ev.id), "name": name},
                )
            )

    # rule catalog: half configured, half pass-through
    catalog = [
        ("DemoHighCPUUsage", ">", "%", 'avg(rate(cpu{cmdb_ci="{{cmdb_ci}}"}[5m]))*100'),
        ("DemoHighMemoryUsage", ">", "%", 'mem_used_pct{cmdb_ci="{{cmdb_ci}}"}'),
        ("DemoHostOutOfMemory", "<", "MB", 'mem_available_mb{cmdb_ci="{{cmdb_ci}}"}'),
        ("DemoDiskWillFillIn4Hours", ">", "%", 'disk_used_pct{cmdb_ci="{{cmdb_ci}}"}'),
        ("DemoHighLatencyP99", ">", "ms", 'p99_latency{cmdb_ci="{{cmdb_ci}}"}'),
        ("DemoTooManyConnections", None, None, None),
        ("DemoPacketLoss", None, None, None),
        ("DemoTargetDown", None, None, None),
        ("DemoHighDiskIO", ">", "iops", 'disk_iops{cmdb_ci="{{cmdb_ci}}"}'),
        ("DemoCertExpiringSoon", "<", "days", 'cert_days_left{cmdb_ci="{{cmdb_ci}}"}'),
    ]
    for name, cmp, unit, vq in catalog:
        db.add(RuleCatalog(alertname=name, comparator=cmp, unit=unit, value_query=vq))

    # threshold overrides — server targets use REAL demo cmdb_ci values
    db.add(
        ThresholdOverride(
            alertname="DemoHighCPUUsage",
            tier="server",
            target_cmdb_ci=servers[1].cmdb_ci,
            value=95.0,
        )
    )
    db.add(
        ThresholdOverride(
            alertname="DemoHighCPUUsage", tier="group", target_group_id=groups[0].id, value=90.0
        )
    )
    db.add(
        ThresholdOverride(
            alertname="DemoHighMemoryUsage", tier="group", target_group_id=groups[2].id, value=85.0
        )
    )
    db.add(
        ThresholdOverride(
            alertname="DemoHostOutOfMemory",
            tier="server",
            target_cmdb_ci=servers[2].cmdb_ci,
            value=512.0,
        )
    )
    db.add(
        ThresholdOverride(
            alertname="DemoDiskWillFillIn4Hours",
            tier="group",
            target_group_id=groups[4].id,
            value=88.0,
        )
    )
    db.add(
        ThresholdOverride(
            alertname="DemoHighLatencyP99",
            tier="server",
            target_cmdb_ci=servers[0].cmdb_ci,
            value=250.0,
        )
    )
    db.add(
        ThresholdOverride(
            alertname="DemoHighDiskIO", tier="group", target_group_id=groups[3].id, value=5000.0
        )
    )

    # notification mutes
    db.add(
        NotificationMute(
            target_type="server",
            target_cmdb_ci=servers[5].cmdb_ci,
            alertname="DemoDiskWillFillIn4Hours",
            reason="planned maintenance",
        )
    )
    db.add(
        NotificationMute(
            target_type="group",
            target_group_id=groups[4].id,
            alertname=None,
            reason="batch tier muted overnight",
        )
    )
    db.add(
        NotificationMute(
            target_type="server",
            target_cmdb_ci=servers[9].cmdb_ci,
            alertname=None,
            reason="decommissioning",
        )
    )
    db.add(
        NotificationMute(
            target_type="all",
            target_cmdb_ci=None,
            alertname="DemoCertExpiringSoon",
            reason="cert renewal in progress",
        )
    )

    await db.commit()
    return {
        "groups": len(GROUPS),
        "servers": 50,
        "incidents": len(incidents),
        "catalog": len(catalog),
        "thresholds": 7,
        "mutes": 4,
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description="Atlas demo / UI-stress seed (idempotent).")
    ap.add_argument("--clear", action="store_true", help="remove demo data and exit")
    args = ap.parse_args()
    async with async_session_factory() as db:
        removed = await clear(db)
        print("CLEARED demo rows:", {k: v for k, v in removed.items() if v})
        if args.clear:
            print("CLEAR_OK")
            return
        created = await seed(db)
        print("SEED_OK", created, "(incl. 1x20-alert, 1x18-label, 1x rich-JSON-timeline)")


if __name__ == "__main__":
    asyncio.run(main())
