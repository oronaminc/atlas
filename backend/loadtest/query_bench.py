"""Hot-query latency at the current alert_events row count.

Times the exact queries the runtime issues (parameter distributions match
seed_events). Run after each seed level (1M / 5M / 10M) to find where they
degrade.

Usage:
    uv run python -m loadtest.query_bench [--iterations 200]
"""

import argparse
import asyncio
import hashlib
import random
import time

import asyncpg

from loadtest.common import DB_DSN, fmt_ms, percentiles

HOSTS = 5000
NAMES = 3

QUERIES = {
    # engine._latest_other_event (dedup collapse target lookup)
    "dedup_latest_by_fp": (
        "SELECT id FROM alert_events WHERE fingerprint = $1 " "ORDER BY received_at DESC LIMIT 1",
        "fp",
    ),
    # correlation_worker.claim_events candidate scan
    "claim_candidates": (
        "SELECT id FROM alert_events WHERE incident_id IS NULL "
        "AND (claimed_at IS NULL OR claimed_at < now() - interval '60 seconds') "
        "ORDER BY received_at ASC LIMIT 100",
        None,
    ),
    # AttributeTimeStrategy.find_incident window scan
    "strategy_window": (
        "SELECT id FROM incidents WHERE group_key = $1 AND status != 'resolved' "
        "AND last_seen >= now() - interval '900 seconds' "
        "ORDER BY last_seen DESC LIMIT 1",
        "gk",
    ),
    # stats overview alerts_24h
    "alerts_24h_count": (
        "SELECT count(*) FROM alert_events WHERE received_at > now() - interval '24 hours'",
        None,
    ),
    # graph window query (incidents in last 24h, capped)
    "graph_incidents_24h": (
        "SELECT id FROM incidents WHERE last_seen >= now() - interval '24 hours' "
        "AND status IN ('open','acknowledged') ORDER BY last_seen DESC LIMIT 2001",
        None,
    ),
    # stats trend: full 24h alert scan (returns rows to python)
    "trend_24h_rows": (
        "SELECT received_at, severity FROM alert_events "
        "WHERE received_at > now() - interval '24 hours'",
        None,
    ),
}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=200)
    args = ap.parse_args()

    conn = await asyncpg.connect(DB_DSN)
    total = await conn.fetchval("SELECT count(*) FROM alert_events")
    size = await conn.fetchval("SELECT pg_size_pretty(pg_total_relation_size('alert_events'))")
    print(f"alert_events: {total} rows, {size} (incl. indexes)\n")
    print(f"{'query':<22} {'p50':>9} {'p95':>9} {'p99':>9} {'rows':>8}")

    rng = random.Random(7)
    for label, (sql, kind) in QUERIES.items():
        lat = []
        nrows = 0
        iters = args.iterations if kind or "count" in label or "claim" in label else 20
        for _ in range(iters):
            if kind == "fp":
                host, name = rng.randrange(HOSTS), rng.randrange(NAMES)
                arg = hashlib.sha256(f"srv-{host:05d}|Alert{name:02d}".encode()).hexdigest()[:64]
                t0 = time.monotonic()
                rows = await conn.fetch(sql, arg)
            elif kind == "gk":
                arg = f"host=srv-{rng.randrange(HOSTS):05d}"
                t0 = time.monotonic()
                rows = await conn.fetch(sql, arg)
            else:
                t0 = time.monotonic()
                rows = await conn.fetch(sql)
            lat.append(time.monotonic() - t0)
            nrows = len(rows)
        p = percentiles(lat)
        print(
            f"{label:<22} {fmt_ms(p['p50']):>9} {fmt_ms(p['p95']):>9} "
            f"{fmt_ms(p['p99']):>9} {nrows:>8}"
        )
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
