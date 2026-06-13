"""Worker metrics server: /metrics + /healthz (heartbeat freshness) + /readyz
(PG reachable). Driven over a real loopback socket (zero-dep raw HTTP client,
same approach as the load-test harness)."""

import asyncio
import time

import app.core.instruments as m
from app.workers.metrics_server import _healthz, heartbeat, start_metrics_server


async def _get(port: int, path: str) -> tuple[int, str]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    raw = await reader.read(65536)
    writer.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    return status, body.decode()


async def _free_port() -> int:
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def test_worker_metrics_and_health_endpoints():
    port = await _free_port()
    server = await start_metrics_server("correlation", port=port, heartbeat_max_age=60)
    try:
        heartbeat("correlation")  # fresh

        status, body = await _get(port, "/metrics")
        assert status == 200
        assert "atlas_worker_last_loop_timestamp_seconds" in body

        status, body = await _get(port, "/healthz")
        assert status == 200 and "ok" in body

        status, _ = await _get(port, "/readyz")
        assert status == 200  # in-memory sqlite engine reachable

        status, _ = await _get(port, "/nope")
        assert status == 404
    finally:
        server.close()
        await server.wait_closed()


def test_healthz_flips_when_heartbeat_stale():
    # fresh
    m.worker_last_loop.set(time.time(), worker="hbtest")
    assert _healthz("hbtest", heartbeat_max_age=60) is True
    # stale (last loop 10 min ago, max age 5 min) -> liveness fails
    m.worker_last_loop.set(time.time() - 600, worker="hbtest")
    assert _healthz("hbtest", heartbeat_max_age=300) is False


async def test_readyz_fails_when_db_unreachable(monkeypatch):
    from app.workers import metrics_server

    class BoomEngine:
        def connect(self):
            raise RuntimeError("pg down")

    monkeypatch.setattr(metrics_server, "engine", BoomEngine())
    port = await _free_port()
    server = await start_metrics_server("sync", port=port)
    try:
        status, body = await _get(port, "/readyz")
        assert status == 503 and "not ready" in body
        # liveness still ok (process alive, just dependency down)
        status, _ = await _get(port, "/healthz")
        assert status == 200
    finally:
        server.close()
        await server.wait_closed()
