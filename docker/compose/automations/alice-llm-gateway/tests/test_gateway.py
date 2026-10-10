"""End-to-end tests over real HTTP: client -> gateway -> fake llama-3090."""
import asyncio
import logging

import httpx

from app import config
from tests.conftest import KEYS, UPSTREAM_KEY, auth, body

CHAT = "/v1/chat/completions"


async def _post(client, caller, rid, **kw):
    return await client.post(CHAT, content=body(rid, **kw), headers={**auth(caller), "Content-Type": "application/json"})


async def _wait_until(cond, timeout=3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached"
        await asyncio.sleep(0.01)


async def test_rejects_missing_or_wrong_key(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway) as c:
        r1 = await c.post(CHAT, content=body("x"))
        r2 = await c.post(CHAT, content=body("x"), headers={"Authorization": "Bearer nope"})
        r3 = await c.post(CHAT, content=body("x"), headers={"Authorization": f"Bearer {UPSTREAM_KEY}"})
    assert [r.status_code for r in (r1, r2, r3)] == [401, 401, 401]
    assert r1.json()["error"]["type"] == "authentication_error"
    assert llama.auth == []  # nothing forwarded


async def test_models_is_public_like_llama_cpp(gateway, llama, caplog):
    """n8n health checks call GET /v1/models without a key (llama.cpp exempts it)."""
    caplog.set_level(logging.INFO, logger="alice-llm-gateway")
    async with httpx.AsyncClient(base_url=gateway) as c:
        r1 = await c.get("/v1/models")
        r2 = await c.get("/v1/models", headers={"Authorization": "Basic abc"})
        chat = await c.post(CHAT, content=body("x"))
    assert r1.status_code == 200 and r1.json()["data"][0]["id"] == "qwen3-vl-30b"
    assert r2.status_code == 200
    assert chat.status_code == 401  # inference still needs a key
    await _wait_until(lambda: '"caller": "anonymous"' in caplog.text)
    assert llama.order == []


async def test_only_allowlisted_paths(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway, headers=auth("chat")) as c:
        assert (await c.post("/v1/completions", content=body("x"))).status_code == 404
        assert (await c.get("/slots")).status_code == 404
        assert (await c.get(CHAT)).status_code == 404  # wrong method
        assert (await c.get("/v1/models")).json()["data"][0]["id"] == "qwen3-vl-30b"
    assert llama.order == []


async def test_caller_key_swapped_for_upstream_key(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway) as c:
        r = await _post(c, "n8n", "a")
    assert r.status_code == 200 and r.json()["id"] == "a"
    assert llama.auth == [f"Bearer {UPSTREAM_KEY}"]


async def test_stream_passes_through_unchanged(gateway, llama):
    async with httpx.AsyncClient() as c:
        async with c.stream("POST", llama.url + CHAT, content=body("s", stream=True, delay=0.1),
                            headers={"Authorization": f"Bearer {UPSTREAM_KEY}"}) as r:
            direct = b"".join([chunk async for chunk in r.aiter_raw()])
        async with c.stream("POST", gateway + CHAT, content=body("s", stream=True, delay=0.1),
                            headers=auth("chat")) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            chunks = [chunk async for chunk in r.aiter_raw()]
    assert b"".join(chunks) == direct
    assert len(chunks) > 1  # streamed, not buffered into one block


async def test_interactive_overtakes_20_queued_background(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway, timeout=30) as c:
        running = asyncio.create_task(_post(c, "extractor", "running", delay=0.5))
        await llama.started.wait()
        queued = []
        for i in range(20):
            queued.append(asyncio.create_task(_post(c, "n8n" if i % 2 else "extractor", f"bg{i}", delay=0.01)))
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.05)
        chat = asyncio.create_task(_post(c, "chat", "chat", delay=0.01))
        results = await asyncio.gather(running, chat, *queued)
    assert all(r.status_code == 200 for r in results)
    assert llama.order[0] == "running"
    assert llama.order[1] == "chat"
    assert llama.order[2:] == [f"bg{i}" for i in range(20)]
    assert llama.max_active == 1


async def test_fifo_between_interactive_callers(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway, timeout=10) as c:
        running = asyncio.create_task(_post(c, "n8n", "running", delay=0.3))
        await llama.started.wait()
        reqs = []
        for i, caller in enumerate(["webui", "chat", "webui", "chat"]):
            reqs.append(asyncio.create_task(_post(c, caller, f"i{i}")))
            await asyncio.sleep(0.02)
        await asyncio.gather(running, *reqs)
    assert llama.order == ["running", "i0", "i1", "i2", "i3"]
    assert llama.max_active == 1


async def test_models_not_queued_behind_busy_slot(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway, timeout=10) as c:
        running = asyncio.create_task(_post(c, "n8n", "running", delay=0.5))
        await llama.started.wait()
        t0 = asyncio.get_running_loop().time()
        r = await c.get("/v1/models", headers=auth("n8n"))
        assert asyncio.get_running_loop().time() - t0 < 0.3
        assert r.status_code == 200
        await running


async def test_abort_while_waiting_is_never_forwarded(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway, timeout=10) as c:
        running = asyncio.create_task(_post(c, "n8n", "running", delay=0.5))
        await llama.started.wait()
        async with httpx.AsyncClient(base_url=gateway, timeout=0.1) as impatient:
            try:
                await _post(impatient, "chat", "gone")
            except httpx.ReadTimeout:
                pass
        health = None
        async def queue_empty():
            nonlocal health
            health = (await c.get("/health")).json()
            return health["queue"]["interactive"] == 0
        for _ in range(100):
            if await queue_empty():
                break
            await asyncio.sleep(0.01)
        assert health["queue"]["interactive"] == 0
        await running
        after = await _post(c, "n8n", "after")
    assert after.status_code == 200
    assert llama.order == ["running", "after"]
    metrics = (await httpx.AsyncClient().get(gateway + "/metrics")).text
    assert 'llm_gateway_requests_total{outcome="client_abort",tier="interactive"}' in metrics


async def test_abort_while_running_frees_slot_and_stops_upstream(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway, timeout=10) as c:
        async with c.stream("POST", CHAT, content=body("long", stream=True, delay=3),
                            headers=auth("extractor")) as r:
            async for _ in r.aiter_raw():
                break  # read one chunk, then hang up
        t0 = asyncio.get_running_loop().time()
        nxt = await _post(c, "chat", "next")
        assert asyncio.get_running_loop().time() - t0 < 1.5
    assert nxt.status_code == 200
    await _wait_until(lambda: "long" in llama.aborted)
    assert llama.order == ["long", "next"]


async def test_upstream_error_status_passed_through_and_slot_freed(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway, timeout=10) as c:
        r = await _post(c, "chat", "err", status=500)
        ok = await _post(c, "chat", "ok")
    assert r.status_code == 500 and r.json()["error"]["message"] == "boom"
    assert ok.status_code == 200


async def test_upstream_down_gives_502_and_frees_slot(gateway, llama):
    real = config.UPSTREAM_URL
    config.UPSTREAM_URL = "http://127.0.0.1:9"  # nothing listens here
    try:
        async with httpx.AsyncClient(base_url=gateway, timeout=10) as c:
            r = await _post(c, "chat", "x")
            health = (await c.get("/health")).json()
            config.UPSTREAM_URL = real
            ok = await _post(c, "chat", "ok")
    finally:
        config.UPSTREAM_URL = real
    assert r.status_code == 502 and r.json()["error"]["type"] == "upstream_unavailable"
    assert health["upstream"] is False and health["slot_busy"] is False
    assert ok.status_code == 200


async def test_metrics_exposed(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway) as c:
        await _post(c, "chat", "m")
        text = (await c.get("/metrics")).text
    for name in ("llm_gateway_queue_length", "llm_gateway_queue_wait_seconds",
                 "llm_gateway_requests_total", "llm_gateway_upstream_seconds", "llm_gateway_slot_busy"):
        assert name in text
    assert 'llm_gateway_queue_length{tier="background"}' in text
    assert KEYS["chat"] not in text
