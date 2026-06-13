import asyncio, json
async def handle(r, w):
    try:
        line = await r.readline()
        clen = 0
        while True:
            h = await r.readline()
            if h in (b"\r\n", b""): break
            if h.lower().startswith(b"content-length:"): clen = int(h.split(b":")[1])
        if clen: await r.readexactly(clen)
        body = json.dumps({"choices":[{"message":{"content":"ROOT CAUSE: disk on db-01 filled to 99%.\nSUMMARY: DiskFull fired repeatedly on db-01; the volume is full. Free space or extend the disk."}}],"usage":{"total_tokens":128}}).encode()
        w.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "+str(len(body)).encode()+b"\r\n\r\n"+body)
        await w.drain()
    except Exception: pass
    finally: w.close()
async def main():
    s = await asyncio.start_server(handle, "127.0.0.1", 18090)
    async with s: await s.serve_forever()
asyncio.run(main())
