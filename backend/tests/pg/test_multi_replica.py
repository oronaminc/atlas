"""Multi-replica safety for the singleton-style periodic workers (sync,
maintenance): a PG advisory lock guarantees only ONE replica runs a pass at a
time, for any N. Real-PG only (advisory locks are a no-op on SQLite).

The claim-based workers (correlation, notification, llm) are covered by
test_pg_concurrency.py (CAS + lease + FOR UPDATE SKIP LOCKED, exactly-once)."""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.locks import advisory_lock

PG_URL = os.environ.get("ATLAS_PG_TEST_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="ATLAS_PG_TEST_URL not set (run scripts/pg_concurrency_test.sh)"
)

N_REPLICAS = 4


@pytest_asyncio.fixture
async def pg_engine():
    # advisory locks are DB-global (not schema-scoped); a plain engine is enough,
    # and each test uses a unique lock name so parallel runs don't collide.
    engine = create_async_engine(PG_URL, pool_size=N_REPLICAS + 2)
    yield engine
    await engine.dispose()


async def test_advisory_lock_is_exclusive_then_released(pg_engine):
    name = f"atlas:test:{uuid.uuid4().hex}"
    async with advisory_lock(name, engine=pg_engine) as a:
        assert a is True
        # a second holder cannot acquire while the first holds it
        async with advisory_lock(name, engine=pg_engine) as b:
            assert b is False
    # released on exit -> re-acquirable
    async with advisory_lock(name, engine=pg_engine) as c:
        assert c is True


async def test_only_one_replica_runs_the_periodic_pass(pg_engine):
    """Models sync/maintenance run_once: N replicas tick simultaneously, the
    guarded body must execute exactly once (the rest skip)."""
    name = f"atlas:test:pass:{uuid.uuid4().hex}"
    ran = 0

    async def tick() -> str:
        nonlocal ran
        async with advisory_lock(name, engine=pg_engine) as acquired:
            if not acquired:
                return "skipped"
            await asyncio.sleep(0.25)  # hold the lock so the peers genuinely overlap
            ran += 1
            return "ran"

    results = await asyncio.gather(*[tick() for _ in range(N_REPLICAS)])

    assert ran == 1, f"expected exactly one pass to run, got {ran}"
    assert results.count("ran") == 1
    assert results.count("skipped") == N_REPLICAS - 1
