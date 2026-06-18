"""Cross-replica mutual exclusion via PostgreSQL advisory locks.

Used by the singleton-style periodic workers (sync, maintenance) so that with
N>=2 replicas only ONE runs a pass at a time. Chosen over the Redis lock
because:
  - no extra dependency — PG is always required (Redis is best-effort here);
  - session-scoped: auto-released when the holder's connection drops (pod crash),
    so no stuck lock and no TTL-steal window;
  - `pg_try_advisory_lock` is non-blocking — the loser simply skips this tick.

Advisory locks are GLOBAL to the PG database (not schema-scoped), so keys are
derived from a stable name. On non-PostgreSQL (SQLite unit tests) there is no
cross-process contention, so the lock is a no-op that always "acquires".
"""

import hashlib
from contextlib import asynccontextmanager

from sqlalchemy import text

from app.db import engine as default_engine


def advisory_key(name: str) -> int:
    """Stable 64-bit signed key for a lock name (pg advisory locks take bigint)."""
    digest = hashlib.blake2b(name.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


@asynccontextmanager
async def advisory_lock(name: str, *, engine=None):
    """Yield True if this process acquired the lock, False if another holds it.

    Holds the lock for the duration of the `async with` block on a dedicated
    connection; releases on exit (or automatically if the connection drops)."""
    eng = engine or default_engine
    if eng.dialect.name != "postgresql":
        # Single-process (SQLite tests): nothing to coordinate against.
        yield True
        return

    key = advisory_key(name)
    conn = await eng.connect()
    acquired = False
    try:
        acquired = bool(
            (await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key})).scalar()
        )
        yield acquired
    finally:
        if acquired:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            except Exception:
                pass  # connection-close releases it regardless
        await conn.close()
