# app.py
import asyncio, json, struct, websockets, requests

OLLAMA_URL = "http://ollama.lan:11434/api/generate"

async def handle(reader, writer):
    # 1) Wyoming Frame lesen (Header 12 Bytes -> len, type)
    header = await reader.readexactly(12)
    length, mtype = struct.unpack(">QI", header)
    payload = await reader.readexactly(length)
    text = payload.decode()

    # 2) LLM anrufen
    res = requests.post(OLLAMA_URL, json={"model":"llama3:8b","prompt":text}).json()
    answer = res["response"]

    # 3) Wyoming-Antwort schreiben (type=1 = TEXT)
    data = answer.encode()
    out = struct.pack(">QI", len(data), 1) + data
    writer.write(out)
    await writer.drain()
    writer.close()

async def main():
    srv = await asyncio.start_server(handle, "0.0.0.0", 10400)
    async with srv: await srv.serve_forever()

asyncio.run(main())
