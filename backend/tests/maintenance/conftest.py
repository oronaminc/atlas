"""Reuse the two-tenant world fixtures from the tenancy suite."""

from tests.tenancy.conftest import (  # noqa: F401
    a_admin,
    a_editor,
    a_viewer,
    b_viewer,
    tenant_a,
    tenant_b,
    world_a,
    world_b,
)
