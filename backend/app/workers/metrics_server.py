"""Tiny stdlib-asyncio HTTP server so each worker pod exposes /metrics,
/healthz and /readyz on METRICS_PORT (workers are loop processes, not HTTP
apps). Zero deps — same raw-socket pattern as loadtest/telegram_stub.

- /metrics  : this process's REGISTRY (its own counters + heartbeat)
- /healthz  : 200 if the worker loop ran within `heartbeat_max_age` (else 503
              -> liveness fails -> k8s restarts a hung-but-alive process)
- /readyz   : 200 if PG reachable (the worker's source of truth); Redis is
              best-effort and never gates readiness (atlas_redis_up surfaces it)
"""

import asyncio
import logging
import time

from sqlalchemy import text

import app.core.instruments as m
from app.core.metrics import CONTENT_TYPE, REGISTRY
from app.db import engine

logger = logging.getLogger(__name__)


def _response(status_line: str, body: bytes, content_type: str) -> bytes:
    return (
        f"HTTP/1.1 {status_line}\r\nContent-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode() + body


async def _readyz() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _healthz(worker: str, heartbeat_max_age: float) -> bool:
    for labels, ts in m.worker_last_loop.samples():
        if labels.get("worker") == worker:
            return (time.time() - ts) <= heartbeat_max_age
    return True  # not yet looped once (startup grace)


async def start_metrics_server(
    worker: str, *, port: int, heartbeat_max_age: float = 300.0
) -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            while True:  # drain headers
                h = await reader.readline()
                if h in (b"\r\n", b""):
                    break
            path = line.split(b" ")[1].decode() if len(line.split(b" ")) > 1 else "/"
            if path == "/metrics":
                writer.write(_response("200 OK", REGISTRY.render().encode(), CONTENT_TYPE))
            elif path == "/healthz":
                ok = _healthz(worker, heartbeat_max_age)
                writer.write(
                    _response(
                        "200 OK" if ok else "503 Service Unavailable",
                        b"ok" if ok else b"stale",
                        "text/plain",
                    )
                )
            elif path == "/readyz":
                ok = await _readyz()
                writer.write(
                    _response(
                        "200 OK" if ok else "503 Service Unavailable",
                        b"ready" if ok else b"not ready",
                        "text/plain",
                    )
                )
            else:
                writer.write(_response("404 Not Found", b"not found", "text/plain"))
            await writer.drain()
        except Exception:
            logger.debug("metrics server request failed", exc_info=True)
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "0.0.0.0", port)  # noqa: S104 (pod-internal)
    logger.info("%s metrics server on :%d", worker, port)
    return server


def heartbeat(worker: str) -> None:
    """Workers call this each loop iteration."""
    m.worker_last_loop.set(time.time(), worker=worker)
