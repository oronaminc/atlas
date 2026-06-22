"""Label-based visibility choke point (IMP §6). What a user SEES is governed by
their user-group -> cmdb_service_l2_code mapping (group_service_codes):

- `get_current_user` (core/deps.py) calls `set_l2_scope` once per request. Admins
  get scope None = see everything (bypass). Non-admins get the (possibly empty)
  set of l2 codes their groups map to.
- A global `do_orm_execute` listener adds `cmdb_service_l2_code IN (scope)` to
  every SELECT on Alert/Incident in a scoped session — endpoints never write the
  filter, so none can forget it. Empty mapping -> IN () -> sees nothing
  (decision F). Alerts/incidents with a NULL l2 are invisible to non-admins.
- Workers/ingest run unscoped (scope never set) and see everything.

Mirrors the tenancy choke point; tenancy is removed in the cleanup stage, after
which this is the only row-visibility mechanism.
"""

import uuid

from sqlalchemy import event, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.alerting import AlertEvent, Incident
from app.models.group import GroupServiceCode, UserGroup

_L2_KEY = "l2_scope"


def set_l2_scope(db, l2_codes: frozenset[str] | None) -> None:
    """None = unscoped (admin/worker, sees all); a (possibly empty) set scopes
    Alert/Incident SELECTs to those l2 codes."""
    db.sync_session.info[_L2_KEY] = l2_codes


def get_l2_scope(db) -> frozenset[str] | None:
    return db.sync_session.info.get(_L2_KEY)


async def allowed_l2_codes(db, user_id: uuid.UUID) -> frozenset[str]:
    """The l2 codes the user's groups map to (union over their group memberships)."""
    rows = (
        await db.execute(
            select(GroupServiceCode.cmdb_service_l2_code)
            .join(UserGroup, UserGroup.group_id == GroupServiceCode.group_id)
            .where(UserGroup.user_id == user_id)
        )
    ).scalars()
    return frozenset(rows)


@event.listens_for(Session, "do_orm_execute")
def _apply_l2_criteria(execute_state) -> None:
    if not execute_state.is_select or execute_state.is_column_load:
        return
    scope = execute_state.session.info.get(_L2_KEY)
    if scope is None:
        return  # admin / worker -> no filter
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            AlertEvent,
            lambda cls: cls.cmdb_service_l2_code.in_(scope),
            include_aliases=True,
            track_closure_variables=False,
        ),
        with_loader_criteria(
            Incident,
            lambda cls: cls.cmdb_service_l2_code.in_(scope),
            include_aliases=True,
            track_closure_variables=False,
        ),
    )
