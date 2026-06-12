"""Stage-2 strategies. Pluggable: rule-based now, LLM stub later."""

from datetime import UTC, datetime, timedelta

from app.models.alerting import Incident, IncidentStatus
from app.services.correlation.strategy import AttributeTimeStrategy, LLMStrategy
from tests.correlation.helpers import alert

NOW = datetime(2026, 6, 10, 1, 0, 0, tzinfo=UTC)


async def make_incident(db, group_key, status=IncidentStatus.open, last_seen=NOW):
    incident = Incident(
        title="t",
        status=status,
        severity="critical",
        group_key=group_key,
        first_seen=last_seen,
        last_seen=last_seen,
        alert_count=1,
    )
    db.add(incident)
    await db.commit()
    return incident


async def test_attaches_to_open_incident_with_same_group_key_in_window(db):
    incident = await make_incident(db, "host=web-01", last_seen=NOW - timedelta(minutes=5))
    found = await AttributeTimeStrategy().find_incident(
        db, alert(), "host=web-01", now=NOW, window_seconds=900
    )
    assert found is not None and found.id == incident.id


async def test_attaches_to_suppressed_incident_without_reopening(db):
    # mute semantics: new alerts keep folding into a suppressed incident,
    # and attaching never flips its status back to open
    incident = await make_incident(
        db, "host=web-01", status=IncidentStatus.suppressed, last_seen=NOW - timedelta(minutes=5)
    )
    found = await AttributeTimeStrategy().find_incident(
        db, alert(), "host=web-01", now=NOW, window_seconds=900
    )
    assert found is not None and found.id == incident.id
    assert found.status == IncidentStatus.suppressed


async def test_ignores_incident_outside_window(db):
    await make_incident(db, "host=web-01", last_seen=NOW - timedelta(minutes=16))
    found = await AttributeTimeStrategy().find_incident(
        db, alert(), "host=web-01", now=NOW, window_seconds=900
    )
    assert found is None


async def test_never_reattaches_to_resolved_incident(db):
    await make_incident(db, "host=web-01", status=IncidentStatus.resolved, last_seen=NOW)
    found = await AttributeTimeStrategy().find_incident(
        db, alert(), "host=web-01", now=NOW, window_seconds=900
    )
    assert found is None


async def test_group_key_none_never_matches(db):
    await make_incident(db, None, last_seen=NOW)
    found = await AttributeTimeStrategy().find_incident(
        db, alert(labels={}), None, now=NOW, window_seconds=900
    )
    assert found is None


async def test_llm_strategy_is_a_stub_returning_none(db):
    await make_incident(db, "host=web-01", last_seen=NOW)
    found = await LLMStrategy().find_incident(
        db, alert(), "host=web-01", now=NOW, window_seconds=900
    )
    assert found is None
