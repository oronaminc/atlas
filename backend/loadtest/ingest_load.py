"""Ingest ceiling: closed-loop ramp over POST /ingest/alertmanager.

Each stage runs N concurrent keep-alive connections for DURATION seconds,
each posting one-alert payloads back-to-back. Reports rps + latency
percentiles + errors per stage; the ceiling is where rps flattens and
p95 climbs.

Usage:
    uv run python -m loadtest.ingest_load [--stages 2,4,8,16,32,64] [--duration 20]
"""

import argparse
import asyncio
import random
import time

from loadtest.common import INGEST_KEY, RawHttpClient, alert_payload, fmt_ms, percentiles

HOSTS = 5000
NAMES = 3  # alertnames per host


async def worker(stop_at: float, latencies: list[float], errors: list[int]):
    client = RawHttpClient()
    rng = random.Random()
    headers = {"X-Atlas-Ingest-Key": INGEST_KEY}
    while time.monotonic() < stop_at:
        body = alert_payload(rng.randrange(HOSTS), rng.randrange(NAMES))
        t0 = time.monotonic()
        try:
            status = await client.post_json("/api/v1/ingest/alertmanager", body, headers)
            latencies.append(time.monotonic() - t0)
            if status != 202:
                errors.append(status)
        except Exception:
            errors.append(-1)
    await client.close()


async def stage(concurrency: int, duration: float) -> dict:
    latencies: list[float] = []
    errors: list[int] = []
    stop_at = time.monotonic() + duration
    t0 = time.monotonic()
    await asyncio.gather(*(worker(stop_at, latencies, errors) for _ in range(concurrency)))
    elapsed = time.monotonic() - t0
    p = percentiles(latencies)
    return {
        "concurrency": concurrency,
        "rps": len(latencies) / elapsed,
        "requests": len(latencies),
        "errors": len(errors),
        **p,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default="2,4,8,16,32,64")
    ap.add_argument("--duration", type=float, default=20.0)
    args = ap.parse_args()

    print(f"{'conc':>5} {'rps':>8} {'p50':>9} {'p95':>9} {'p99':>9} {'errors':>7}")
    for c in [int(x) for x in args.stages.split(",")]:
        r = await stage(c, args.duration)
        print(
            f"{r['concurrency']:>5} {r['rps']:>8.0f} {fmt_ms(r['p50']):>9} "
            f"{fmt_ms(r['p95']):>9} {fmt_ms(r['p99']):>9} {r['errors']:>7}"
        )


if __name__ == "__main__":
    asyncio.run(main())
