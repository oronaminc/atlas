"""Shared helpers for the load-test harness (stdlib + asyncpg only)."""

import asyncio
import json
import os
import time

DB_DSN = os.environ.get("LOAD_PG_DSN", "postgresql://atlas:atlas@127.0.0.1:5432/atlas")
BASE_HOST = os.environ.get("LOAD_HOST", "127.0.0.1")
BASE_PORT = int(os.environ.get("LOAD_PORT", "8000"))
INGEST_KEY = os.environ.get("INGEST_API_KEY", "load-test-key")


def percentiles(samples: list[float], ps=(50, 95, 99)) -> dict[str, float]:
    if not samples:
        return {f"p{p}": 0.0 for p in ps}
    s = sorted(samples)
    return {f"p{p}": s[min(len(s) - 1, int(len(s) * p / 100))] for p in ps}


def fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f}ms"


class RawHttpClient:
    """Minimal HTTP/1.1 keep-alive client over asyncio sockets.
    Avoids httpx/aiohttp client-side overhead so the harness is never
    the bottleneck on small CPU budgets."""

    def __init__(self, host: str = BASE_HOST, port: int = BASE_PORT):
        self.host, self.port = host, port
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        # serialize request/response per connection (open-loop pacing may
        # otherwise interleave two requests on one socket)
        self.lock = asyncio.Lock()

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)

    async def close(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass

    async def post_json(self, path: str, body: dict, headers: dict | None = None) -> int:
        if self.writer is None:
            await self.connect()
        payload = json.dumps(body).encode()
        head = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {self.host}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
        )
        for k, v in (headers or {}).items():
            head += f"{k}: {v}\r\n"
        head += "\r\n"
        try:
            self.writer.write(head.encode() + payload)
            await self.writer.drain()
            status_line = await self.reader.readline()
            status = int(status_line.split()[1])
            content_length = 0
            chunked = False
            while True:
                line = await self.reader.readline()
                if line in (b"\r\n", b""):
                    break
                lower = line.lower()
                if lower.startswith(b"content-length:"):
                    content_length = int(line.split(b":")[1])
                if lower.startswith(b"transfer-encoding:") and b"chunked" in lower:
                    chunked = True
            if chunked:
                while True:
                    size_line = await self.reader.readline()
                    size = int(size_line.strip() or b"0", 16)
                    if size == 0:
                        await self.reader.readline()
                        break
                    await self.reader.readexactly(size + 2)
            elif content_length:
                await self.reader.readexactly(content_length)
            return status
        except Exception:
            await self.close()
            self.reader = self.writer = None
            raise


def alert_payload(host_id: int, name_id: int, severity: str = "warning") -> dict:
    """Alertmanager v4 webhook body: one alert from a 5k-host fleet."""
    return {
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": f"Alert{name_id:02d}",
                    "severity": severity,
                    "host": f"srv-{host_id:05d}",
                },
                "annotations": {"summary": f"Alert{name_id:02d} on srv-{host_id:05d}"},
                "startsAt": "2026-06-12T00:00:00Z",
            }
        ]
    }


class Sampler:
    """Background 1Hz sampler for queue-depth style gauges."""

    def __init__(self, fn, interval: float = 1.0):
        self.fn = fn
        self.interval = interval
        self.samples: list[tuple[float, float]] = []
        self._task = None
        self._t0 = None

    async def _run(self):
        while True:
            value = await self.fn()
            self.samples.append((time.monotonic() - self._t0, value))
            await asyncio.sleep(self.interval)

    def start(self):
        self._t0 = time.monotonic()
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
