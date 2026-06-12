"""Local Telegram API stub: 200 OK to every sendMessage, counts requests,
optional artificial latency (real Telegram round-trip ≈ 50-150ms).

Usage:
    uv run python -m loadtest.telegram_stub [--port 18082] [--latency-ms 50]
"""

import argparse
import asyncio
import json
import time

COUNT = {"n": 0, "t0": None}


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, latency: float):
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            content_length = 0
            while True:
                h = await reader.readline()
                if h in (b"\r\n", b""):
                    break
                if h.lower().startswith(b"content-length:"):
                    content_length = int(h.split(b":")[1])
            if content_length:
                await reader.readexactly(content_length)
            if latency:
                await asyncio.sleep(latency)
            COUNT["n"] += 1
            if COUNT["t0"] is None:
                COUNT["t0"] = time.monotonic()
            body = json.dumps({"ok": True}).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode()
                + body
            )
            await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18082)
    ap.add_argument("--latency-ms", type=float, default=50)
    args = ap.parse_args()

    server = await asyncio.start_server(
        lambda r, w: handle(r, w, args.latency_ms / 1000), "127.0.0.1", args.port
    )
    print(f"telegram stub on :{args.port} (latency {args.latency_ms}ms)")

    async def report():
        while True:
            await asyncio.sleep(5)
            if COUNT["t0"]:
                rate = COUNT["n"] / (time.monotonic() - COUNT["t0"])
                print(f"  sends={COUNT['n']} avg_rate={rate:.1f}/s")

    asyncio.create_task(report())
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
