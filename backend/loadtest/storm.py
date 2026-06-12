"""Alert storm: blast N alerts as fast as possible (burst), then watch the
system recover. Measures ingest-side error rate under burst + correlation
backlog drain + notification queue depth.

Usage:
    uv run python -m loadtest.storm [--alerts 10000] [--concurrency 32] [--watch 180]
"""

import argparse
import asyncio
import random
import time

import asyncpg

from loadtest.common import (
    DB_DSN,
    INGEST_KEY,
    RawHttpClient,
    Sampler,
    alert_payload,
    fmt_ms,
    percentiles,
)

HOSTS = 5000
NAMES = 3


async def blast(total: int, concurrency: int):
    latencies: list[float] = []
    errors: list[int] = []
    counter = {"n": 0}

    async def worker():
        client = RawHttpClient()
        rng = random.Random()
        headers = {"X-Atlas-Ingest-Key": INGEST_KEY}
        while True:
            if counter["n"] >= total:
                break
            counter["n"] += 1
            t0 = time.monotonic()
            try:
                s = await client.post_json(
                    "/api/v1/ingest/alertmanager",
                    alert_payload(rng.randrange(HOSTS), rng.randrange(NAMES)),
                    headers,
                )
                latencies.append(time.monotonic() - t0)
                if s != 202:
                    errors.append(s)
            except Exception:
                errors.append(-1)
        await client.close()

    t0 = time.monotonic()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return latencies, errors, time.monotonic() - t0


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alerts", type=int, default=10000)
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--watch", type=float, default=180)
    args = ap.parse_args()

    pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=2)

    async def gauges():
        row = await pool.fetchrow(
            "SELECT (SELECT count(*) FROM alert_events WHERE incident_id IS NULL) AS backlog,"
            " (SELECT count(*) FROM notifications WHERE status='pending') AS notif_pending,"
            " (SELECT count(*) FROM incidents) AS incidents"
        )
        return row

    samples = []

    async def sample_fn():
        row = await gauges()
        samples.append((time.monotonic() - t_start, dict(row)))
        return row["backlog"]

    t_start = time.monotonic()
    sampler = Sampler(sample_fn)
    sampler.start()

    latencies, errors, elapsed = await blast(args.alerts, args.concurrency)
    p = percentiles(latencies)
    print(
        f"burst: {len(latencies)} accepted in {elapsed:.1f}s = {len(latencies) / elapsed:.0f}/s, "
        f"{len(errors)} errors, p50 {fmt_ms(p['p50'])} "
        f"p95 {fmt_ms(p['p95'])} p99 {fmt_ms(p['p99'])}"
    )

    # watch recovery
    t0 = time.monotonic()
    while time.monotonic() - t0 < args.watch:
        b = await pool.fetchval("SELECT count(*) FROM alert_events WHERE incident_id IS NULL")
        if b == 0:
            break
        await asyncio.sleep(2)
    await sampler.stop()

    print("t(s)  backlog  notif_pending  incidents")
    for t, row in samples[:: max(1, len(samples) // 30)]:
        print(f"{t:5.0f}  {row['backlog']:>7}  {row['notif_pending']:>13}  {row['incidents']:>9}")
    final = samples[-1][1]
    print(
        f"final: backlog={final['backlog']} notif_pending={final['notif_pending']} "
        f"incidents={final['incidents']} after {samples[-1][0]:.0f}s"
    )
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
