"""Fixtures: a fake llama-3090 and the real gateway, both served by uvicorn on
random local ports, so tests exercise real HTTP (streaming, disconnects)."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

UPSTREAM_KEY = "upstream-secret"
KEYS = {"chat": "key-chat", "webui": "key-webui", "n8n": "key-n8n", "extractor": "key-extractor"}

_tmp = tempfile.mkdtemp()
with open(os.path.join(_tmp, "llama_api_key"), "w") as fh:
    fh.write(UPSTREAM_KEY + "\n")
with open(os.path.join(_tmp, "clients"), "w") as fh:
    fh.write(
        "# name tier key\n"
        f"chat interactive {KEYS['chat']}\n"
        f"webui interactive {KEYS['webui']}\n"
        f"n8n background {KEYS['n8n']}\n"
        f"extractor background {KEYS['extractor']}\n"
    )
os.environ["UPSTREAM_KEY_FILE"] = os.path.join(_tmp, "llama_api_key")
os.environ["CLIENTS_FILE"] = os.path.join(_tmp, "clients")


class FakeLlama:
    """Records order/concurrency; the request body controls its behaviour:
    {"id": str, "delay": seconds, "stream": bool, "status": int}."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.active = 0
        self.max_active = 0
        self.auth: list[str | None] = []
        self.finished: list[str] = []
        self.aborted: list[str] = []
        self.started = asyncio.Event()

    def app(self) -> Starlette:
        async def completions(request):
            body = await request.json()
            rid = body.get("id", "?")
            self.auth.append(request.headers.get("authorization"))
            if request.headers.get("authorization") != f"Bearer {UPSTREAM_KEY}":
                return JSONResponse({"error": {"code": 401}}, status_code=401)
            self.order.append(rid)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.set()
            delay = float(body.get("delay", 0))
            if body.get("status"):
                self.active -= 1
                return JSONResponse({"error": {"message": "boom"}}, status_code=body["status"])
            if body.get("stream"):
                async def gen():
                    try:
                        for i in range(5):
                            await asyncio.sleep(delay / 5)
                            yield f'data: {{"id":"{rid}","choices":[{{"delta":{{"content":"t{i}"}}}}]}}\n\n'.encode()
                        yield b"data: [DONE]\n\n"
                        self.finished.append(rid)
                    finally:
                        self.active -= 1
                        if rid not in self.finished:
                            self.aborted.append(rid)
                return StreamingResponse(gen(), media_type="text/event-stream")
            try:
                await asyncio.sleep(delay)
            finally:
                self.active -= 1
            self.finished.append(rid)
            return JSONResponse({"id": rid, "choices": [{"message": {"content": "ok"}}]})

        async def models(request):
            return JSONResponse({"data": [{"id": "qwen3-vl-30b"}]})

        async def health(request):
            return JSONResponse({"status": "ok"})

        return Starlette(routes=[
            Route("/v1/chat/completions", completions, methods=["POST"]),
            Route("/v1/models", models),
            Route("/health", health),
        ])


async def _serve(app) -> tuple[uvicorn.Server, asyncio.Task, int]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, port


@pytest.fixture
async def llama():
    fake = FakeLlama()
    server, task, port = await _serve(fake.app())
    fake.url = f"http://127.0.0.1:{port}"
    yield fake
    server.should_exit = True
    await task


@pytest.fixture
async def gateway(llama):
    from app import config, main

    config.UPSTREAM_URL = llama.url
    server, task, port = await _serve(main.app)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


def auth(caller: str) -> dict:
    return {"Authorization": f"Bearer {KEYS[caller]}"}


def body(rid: str, **kw) -> bytes:
    return json.dumps({"id": rid, "model": "qwen3-vl-30b", "messages": [], **kw}).encode()
