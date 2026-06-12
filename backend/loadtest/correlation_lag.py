"""Correlation keep-up: ingest at a fixed rate while sampling the
uncorrelated backlog (alert_events.incident_id IS NULL) once per second.

If backlog grows linearly while the rate holds, the worker can't keep up:
its max drain rate is the slope after ingest stops.

Usage:
    uv run python -m loadtest.correlation_lag [--rate 50] [--duration 30] [--drain-wait 120]
"""

import argparse
import asyncio
import random
import time

import asyncpg

from loadtest.common import DB_DSN, INGEST_KEY, RawHttpClient, Sampler, alert_payload

HOSTS = 5000
NAMES = 3


async def backlog(pool) -> int:
    return await pool.fetchval("SELECT count(*) FROM alert_events WHERE incident_id IS NULL")


async def paced_ingest(rate: float, duration: float):
    """Open-loop: fire at the target rate regardless of response times."""
    n_conns = max(2, min(32, int(rate / 25) + 1))
    clients = [RawHttpClient() for _ in range(n_conns)]
    headers = {"X-Atlas-Ingest-Key": INGEST_KEY}
    rng = random.Random()
    interval = 1.0 / rate
    sent = errors = 0
    t0 = time.monotonic()
    i = 0

    async def fire(client):
        nonlocal sent, errors
        try:
            async with client.lock:
                s = await client.post_json(
                    "/api/v1/ingest/alertmanager",
                    alert_payload(rng.randrange(HOSTS), rng.randrange(NAMES)),
                    headers,
                )
            sent += 1
            if s != 202:
                errors += 1
        except Exception:
            errors += 1

    pending = set()
    while time.monotonic() - t0 < duration:
        target = t0 + i * interval
        delay = target - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        task = asyncio.create_task(fire(clients[i % n_conns]))
        pending.add(task)
        task.add_done_callback(pending.discard)
        i += 1
    if pending:
        await asyncio.wait(pending, timeout=10)
    for c in clients:
        await c.close()
    return sent, errors, time.monotonic() - t0


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=50)
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--drain-wait", type=float, default=120)
    args = ap.parse_args()

    pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=2)
    sampler = Sampler(lambda: backlog(pool))
    sampler.start()

    sent, errors, elapsed = await paced_ingest(args.rate, args.duration)
    print(f"ingested {sent} ({errors} errors) in {elapsed:.1f}s = {sent / elapsed:.0f}/s")

    # wait for the worker to drain
    t0 = time.monotonic()
    while time.monotonic() - t0 < args.drain_wait:
        b = await backlog(pool)
        if b == 0:
            break
        await asyncio.sleep(1)
    await sampler.stop()
    await pool.close()

    print("t(s)  backlog")
    for t, v in sampler.samples:
        print(f"{t:5.0f}  {int(v)}")
    peak = max(v for _, v in sampler.samples)
    drained = [(t, v) for t, v in sampler.samples if v == peak]
    end_zero = next((t for t, v in sampler.samples if t > drained[0][0] and v == 0), None)
    if end_zero:
        drain_rate = peak / (end_zero - drained[0][0]) if end_zero > drained[0][0] else 0
        print(
            f"peak backlog {int(peak)}, drained in {end_zero - drained[0][0]:.0f}s "
            f"≈ {drain_rate:.1f} events/s worker throughput"
        )
    else:
        print(f"peak backlog {int(peak)}, NOT drained within {args.drain_wait}s")


if __name__ == "__main__":
    asyncio.run(main())
