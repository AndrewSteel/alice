"""QA / red-team checks for PROJ-111 (in addition to test_gateway.py)."""
import asyncio
import json
import time

import httpx

from tests.conftest import KEYS, UPSTREAM_KEY, auth, body

CHAT = "/v1/chat/completions"


async def _post(client, caller, rid, headers=None, **kw):
    return await client.post(CHAT, content=body(rid, **kw), headers={**auth(caller), **(headers or {})})


async def test_background_cannot_claim_interactive_tier(gateway, llama):
    spoof = {"X-Priority": "interactive", "X-Tier": "interactive", "X-Caller": "chat"}
    async with httpx.AsyncClient(base_url=gateway, timeout=10) as c:
        running = asyncio.create_task(_post(c, "n8n", "running", delay=0.3))
        await llama.started.wait()
        spoofed = asyncio.create_task(_post(c, "n8n", "spoofed", headers=spoof, priority="interactive", tier="interactive"))
        await asyncio.sleep(0.05)
        chat = asyncio.create_task(_post(c, "chat", "chat"))
        await asyncio.gather(running, spoofed, chat)
    assert llama.order == ["running", "chat", "spoofed"]


async def test_auth_header_edge_cases(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway) as c:
        ok_lower = await c.post(CHAT, content=body("a"), headers={"Authorization": f"bearer {KEYS['chat']}"})
        cases = [
            {"Authorization": f"Bearer {KEYS['chat']}x"},
            {"Authorization": f"Bearer {KEYS['chat'][:-1]}"},
            {"Authorization": "Bearer"},
            {"Authorization": KEYS["chat"]},  # no scheme
            {"Authorization": f"Basic {KEYS['chat']}"},
            {"X-Api-Key": KEYS["chat"]},
        ]
        codes = [(await c.post(CHAT, content=body("b"), headers=h)).status_code for h in cases]
    assert ok_lower.status_code == 200
    assert codes == [401] * len(cases)
    assert llama.order == ["a"]


async def test_path_variants_are_not_proxied(gateway, llama):
    async with httpx.AsyncClient(base_url=gateway, headers=auth("chat")) as c:
        for path in ("/v1/chat/completions/", "/v1//chat/completions", "/V1/chat/completions",
                     "/v1/chat/completions/../models", "/props", "/slots", "/v1/embeddings",
                     "/models/load", "/apply-template"):
            r = await c.post(path, content=body("x"))
            assert r.status_code == 404, path
    assert llama.order == []


async def test_body_too_large_rejected_before_forwarding(gateway, llama, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MAX_BODY_BYTES", 1000)
    async with httpx.AsyncClient(base_url=gateway) as c:
        r = await _post(c, "chat", "big", pad="x" * 2000)
    assert r.status_code == 413
    assert llama.order == []


async def test_abort_while_running_non_stream_frees_slot(gateway, llama):
    """n8n/extractor style (no streaming) caller times out mid-generation."""
    async with httpx.AsyncClient(base_url=gateway, timeout=0.2) as impatient:
        try:
            await _post(impatient, "extractor", "slow", delay=3)
        except httpx.ReadTimeout:
            pass
    async with httpx.AsyncClient(base_url=gateway, timeout=10) as c:
        t0 = time.monotonic()
        r = await _post(c, "chat", "next")
        assert time.monotonic() - t0 < 1.0
    assert r.status_code == 200
    assert llama.order == ["slow", "next"]


async def test_load_mixed_200_requests(gateway, llama):
    """200 concurrent requests: never more than one active upstream, all served,
    and every interactive request that was queued behind a running request is
    served before all background requests queued at that time."""
    limits = httpx.Limits(max_connections=300)
    async with httpx.AsyncClient(base_url=gateway, timeout=60, limits=limits) as c:
        running = asyncio.create_task(_post(c, "n8n", "running", delay=2))
        await llama.started.wait()
        tasks = []
        for i in range(200):
            caller = "chat" if i % 10 == 0 else ("n8n" if i % 2 else "extractor")
            tasks.append(asyncio.create_task(_post(c, caller, f"{caller}-{i}", delay=0.001)))
        results = await asyncio.gather(running, *tasks)
    assert all(r.status_code == 200 for r in results)
    assert llama.max_active == 1
    assert len(llama.order) == 201
    served = llama.order[1:]
    interactive = [rid for rid in served if rid.startswith("chat-")]
    assert served[: len(interactive)] == interactive  # all 20 chats first, in arrival order
    async with httpx.AsyncClient(base_url=gateway) as c:
        health = (await c.get("/health")).json()
    assert health["queue"] == {"interactive": 0, "background": 0} and health["slot_busy"] is False


async def test_gateway_overhead_on_empty_queue(gateway, llama):
    async with httpx.AsyncClient(timeout=10) as c:
        hdr = {"Authorization": f"Bearer {UPSTREAM_KEY}"}
        for _ in range(5):  # warm connections
            await c.post(llama.url + CHAT, content=body("w"), headers=hdr)
            await c.post(gateway + CHAT, content=body("w"), headers=auth("chat"))
        direct, via = [], []
        for _ in range(30):
            t0 = time.perf_counter()
            await c.post(llama.url + CHAT, content=body("d"), headers=hdr)
            direct.append(time.perf_counter() - t0)
            t0 = time.perf_counter()
            await c.post(gateway + CHAT, content=body("g"), headers=auth("chat"))
            via.append(time.perf_counter() - t0)
    direct.sort(), via.sort()
    overhead_ms = (via[15] - direct[15]) * 1000
    print(f"median overhead: {overhead_ms:.1f} ms")
    assert overhead_ms < 50


async def test_secrets_never_leak(gateway, llama, capfd, caplog):
    async with httpx.AsyncClient(base_url=gateway) as c:
        await _post(c, "chat", "s")
        await c.post(CHAT, content=body("x"), headers={"Authorization": "Bearer wrong-guess"})
        health = (await c.get("/health")).text
        metrics = (await c.get("/metrics")).text
    out = capfd.readouterr()
    logs = caplog.text + out.out + out.err
    for secret in (*KEYS.values(), UPSTREAM_KEY, "wrong-guess"):
        assert secret not in health and secret not in metrics and secret not in logs
    assert json.loads(health)["status"] == "ok"
