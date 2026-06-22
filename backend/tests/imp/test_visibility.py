"""IMP stage 6: l2 visibility choke point. Non-admins see only Alert/Incident
rows whose cmdb_service_l2_code their groups map to; admins (scope None) see all;
empty mapping sees nothing (decision F). NULL-l2 rows are invisible to scoped
sessions."""

from sqlalchemy import func, select

from app.core.visibility import allowed_l2_codes, set_l2_scope
from app.models.alerting import AlertEvent, Incident, IncidentStatus
from app.models.base import utcnow
from app.models.group import Group, GroupServiceCode, UserGroup
from app.models.user import GlobalRole, User

NOW = utcnow()


def _inc(l2):
    return Incident(
        title=f"i-{l2}",
        status=IncidentStatus.open,
        severity="critical",
        group_key=f"cmdb_service_l2_code={l2}" if l2 else None,
        first_seen=NOW,
        last_seen=NOW,
        alert_count=0,
        cmdb_service_l2_code=l2,
    )


async def _seed(db):
    db.add_all([_inc("A"), _inc("B"), _inc(None)])
    await db.flush()


async def _count(db):
    return (await db.execute(select(func.count()).select_from(Incident))).scalar_one()


async def test_admin_scope_none_sees_all(db):
    await _seed(db)
    set_l2_scope(db, None)
    assert await _count(db) == 3  # incl. the NULL-l2 one
    set_l2_scope(db, None)


async def test_scoped_sees_only_mapped_l2(db):
    await _seed(db)
    set_l2_scope(db, frozenset({"A"}))
    incs = (await db.execute(select(Incident))).scalars().all()
    assert [i.cmdb_service_l2_code for i in incs] == ["A"]
    set_l2_scope(db, None)


async def test_empty_mapping_sees_nothing(db):
    await _seed(db)
    set_l2_scope(db, frozenset())
    assert await _count(db) == 0  # decision F
    set_l2_scope(db, None)


async def test_filter_also_applies_to_alerts(db):
    db.add(
        AlertEvent(
            fingerprint="a",
            source="am",
            name="n",
            severity="info",
            status="firing",
            labels={},
            annotations={},
            starts_at=NOW,
            received_at=NOW,
            cmdb_service_l2_code="A",
        )
    )
    db.add(
        AlertEvent(
            fingerprint="b",
            source="am",
            name="n",
            severity="info",
            status="firing",
            labels={},
            annotations={},
            starts_at=NOW,
            received_at=NOW,
            cmdb_service_l2_code="B",
        )
    )
    await db.flush()
    set_l2_scope(db, frozenset({"A"}))
    rows = (await db.execute(select(AlertEvent))).scalars().all()
    assert [r.cmdb_service_l2_code for r in rows] == ["A"]
    set_l2_scope(db, None)


async def test_allowed_l2_codes_unions_group_mappings(db):
    user = User(email="u@x.io", username="u", role=GlobalRole.viewer)
    db.add(user)
    await db.flush()
    g = Group(name="g1")
    db.add(g)
    await db.flush()
    db.add(UserGroup(user_id=user.id, group_id=g.id))
    db.add(GroupServiceCode(group_id=g.id, cmdb_service_l2_code="A"))
    db.add(GroupServiceCode(group_id=g.id, cmdb_service_l2_code="B"))
    await db.flush()
    assert await allowed_l2_codes(db, user.id) == frozenset({"A", "B"})
