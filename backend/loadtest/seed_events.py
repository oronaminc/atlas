"""Bulk-seed alert_events to a target row count via asyncpg COPY.

Distribution mirrors a 5k-server fleet: fingerprint cardinality =
hosts × alertnames, received_at spread over --days. Most rows carry an
incident_id (correlated history) so the worker's IS NULL scan reflects
reality.

Usage:
    uv run python -m loadtest.seed_events --rows 1000000 [--days 30]
"""

import argparse
import asyncio
import hashlib
import json
import random
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg

from loadtest.common import DB_DSN

HOSTS = 5000
NAMES = 3
BATCH = 50_000


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    conn = await asyncpg.connect(DB_DSN)

    existing = await conn.fetchval("SELECT count(*) FROM alert_events")
    todo = args.rows - existing
    if todo <= 0:
        print(f"already at {existing} rows")
        await conn.close()
        return

    # one synthetic incident to attach history rows to (FK target)
    incident_id = await conn.fetchval(
        """INSERT INTO incidents (id, title, status, severity, group_key, first_seen,
           last_seen, alert_count, created_at, updated_at)
           VALUES ($1, 'seed-history', 'resolved', 'info', 'host=seed', now(), now(), 0,
           now(), now())
           RETURNING id""",
        uuid.uuid4(),
    )

    rng = random.Random(42)
    now = datetime.now(UTC)
    span = timedelta(days=args.days)
    written = 0
    columns = [
        "id",
        "fingerprint",
        "source",
        "name",
        "severity",
        "status",
        "labels",
        "annotations",
        "starts_at",
        "received_at",
        "incident_id",
        "dedup_count",
        "created_at",
        "updated_at",
    ]
    while written < todo:
        n = min(BATCH, todo - written)
        # text-format COPY: asyncpg has no binary encoder for jsonb
        lines = []
        for _ in range(n):
            host = rng.randrange(HOSTS)
            name = rng.randrange(NAMES)
            fp = hashlib.sha256(f"srv-{host:05d}|Alert{name:02d}".encode()).hexdigest()[:64]
            ts = (now - span * rng.random()).isoformat()
            labels = json.dumps({"host": f"srv-{host:05d}"})
            lines.append(
                f"{uuid.uuid4()}\t{fp}\talertmanager\tAlert{name:02d}\twarning\tfiring"
                f"\t{labels}\t{{}}\t{ts}\t{ts}\t{incident_id}\t1\t{ts}\t{ts}\n"
            )
        import io

        await conn.copy_to_table(
            "alert_events",
            source=io.BytesIO("".join(lines).encode()),
            columns=columns,
            format="text",
        )
        written += n
        print(f"  seeded {existing + written}/{args.rows}")
    await conn.execute("ANALYZE alert_events")
    print(
        f"done: {await conn.fetchval('SELECT count(*) FROM alert_events')} rows, ANALYZE complete"
    )
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
