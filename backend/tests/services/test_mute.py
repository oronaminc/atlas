"""Mute matching: exact, alertname-wildcard, target-wildcard ('all'), group via
membership, multi-pair 'all-muted' rule, missing cmdb_ci, and tenant isolation."""

import uuid

from app.models.delivery import NotificationMute
from app.models.server import Server, ServerGroup
from app.services.mute import is_incident_muted
from tests.notifications.helpers import seed_incident_with_events


async def _mute(db, **kw):
    m = NotificationMute(**kw)
    db.add(m)
    await db.flush()
    return m


async def test_no_mutes_not_muted(db):
    inc = await seed_incident_with_events(db, [("X", "HostOutOfMemory")])
    assert await is_incident_muted(db, inc) is False


async def test_exact_server_alertname(db):
    inc = await seed_incident_with_events(db, [("X", "HostOutOfMemory")])
    await _mute(db, target_type="server", target_cmdb_ci="X", alertname="HostOutOfMemory")
    assert await is_incident_muted(db, inc) is True


async def test_server_mute_different_alertname_not_muted(db):
    inc = await seed_incident_with_events(db, [("X", "HostHighCPU")])
    await _mute(db, target_type="server", target_cmdb_ci="X", alertname="HostOutOfMemory")
    assert await is_incident_muted(db, inc) is False


async def test_alertname_wildcard_mutes_all_rules_for_server(db):
    inc = await seed_incident_with_events(db, [("X", "AnyAlert")])
    await _mute(db, target_type="server", target_cmdb_ci="X", alertname=None)  # all rules
    assert await is_incident_muted(db, inc) is True


async def test_all_targets_for_one_alertname(db):
    muted = await seed_incident_with_events(db, [("X", "HostOutOfMemory")])
    other = await seed_incident_with_events(db, [("X", "HostHighCPU")])
    await _mute(db, target_type="all", alertname="HostOutOfMemory")  # rule across all targets
    assert await is_incident_muted(db, muted) is True
    assert await is_incident_muted(db, other) is False


async def test_group_mute_via_membership(db):
    g = ServerGroup(name="db-tier")
    db.add(g)
    await db.flush()
    db.add(Server(name="X", cmdb_ci="X", server_group_id=g.id))
    await db.flush()
    inc = await seed_incident_with_events(db, [("X", "HostOutOfMemory")])
    await _mute(db, target_type="group", target_group_id=g.id, alertname="HostOutOfMemory")
    assert await is_incident_muted(db, inc) is True


async def test_multi_pair_all_must_be_muted(db):
    inc = await seed_incident_with_events(db, [("X", "HostOutOfMemory"), ("X", "HostHighCPU")])
    m = await _mute(db, target_type="server", target_cmdb_ci="X", alertname="HostOutOfMemory")
    # only one of two pairs muted -> incident NOT muted (a live alert remains)
    assert await is_incident_muted(db, inc) is False
    # mute the second too -> now fully muted
    await _mute(db, target_type="server", target_cmdb_ci="X", alertname="HostHighCPU")
    assert await is_incident_muted(db, inc) is True
    assert m is not None


async def test_missing_cmdb_ci_falls_through(db):
    inc = await seed_incident_with_events(db, [(None, "HostOutOfMemory")])
    await _mute(db, target_type="server", target_cmdb_ci="X", alertname="HostOutOfMemory")
    assert await is_incident_muted(db, inc) is False  # no cmdb_ci -> server mute can't match


async def test_disabled_mute_ignored(db):
    inc = await seed_incident_with_events(db, [("X", "HostOutOfMemory")])
    await _mute(
        db, target_type="server", target_cmdb_ci="X", alertname="HostOutOfMemory", enabled=False
    )
    assert await is_incident_muted(db, inc) is False


async def test_tenant_isolation(db):
    t_a, t_b = uuid.uuid4(), uuid.uuid4()
    inc_b = await seed_incident_with_events(db, [("X", "HostOutOfMemory")], tenant_id=t_b)
    # mute belongs to tenant A only
    await _mute(
        db, target_type="server", target_cmdb_ci="X", alertname="HostOutOfMemory", tenant_id=t_a
    )
    assert await is_incident_muted(db, inc_b) is False  # A's mute never affects B
