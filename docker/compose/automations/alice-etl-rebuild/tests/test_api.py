"""HTTP interface (PROJ-122 will use it) and progress under load (AK-20)."""
import asyncio
import time

import httpx

from app import main
from app.clients import DetectionClient, RegistryClient


def _client(env):
    svc = main.Service(env.settings, env.pool, env.registry, env.detection)
    svc.rebuilds = env.rebuilds
    svc.reconciler = env.reconciler
    main.app.state.svc = svc
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://etl")


async def test_http_flow(env):
    await env.add(3)
    async with _client(env) as c:
        assert (await c.get("/rebuilds/current")).status_code == 404
        assert (await c.post("/rebuilds", json={"start_stage": "classify", "started_by": ""})).status_code == 422
        assert (await c.post("/rebuilds", json={"start_stage": "classify", "kind": "x", "started_by": "a"})).status_code == 422
        assert (await c.post("/rebuilds", json={"start_stage": "detect", "started_by": "a"})).status_code == 422
        r = await c.post("/rebuilds", json={"start_stage": "classify", "kind": "document", "started_by": "admin"})
        assert r.status_code == 201
        rid = r.json()["id"]
        r = await c.post("/rebuilds", json={"start_stage": "extract", "started_by": "admin"})
        assert r.status_code == 409 and r.json()["run"]["id"] == rid  # AK-7
        assert (await c.get("/rebuilds/current")).json()["id"] == rid
        assert (await c.post(f"/rebuilds/{rid}/pause")).json()["status"] == "paused"
        assert (await c.post(f"/rebuilds/{rid}/pause")).status_code == 409
        assert (await c.post(f"/rebuilds/{rid}/resume")).json()["status"] == "running"
        assert (await c.post(f"/rebuilds/{rid}/explode")).status_code == 404
        assert (await c.get("/rebuilds/999999")).status_code == 404
        p = await env.drive(rid)
        assert p["status"] == "done"
        body = (await c.get(f"/rebuilds/{rid}")).json()
        assert body["status"] == "done" and body["finished"] == 3
        assert (await c.get(f"/rebuilds/{rid}/errors")).json() == {"total": 0, "items": []}
        assert (await c.get("/rebuilds?limit=5")).json()["total"] == 1
        r = await c.post("/reconcile")
        assert r.status_code == 202
        assert (await c.post("/reconcile")).status_code == 409  # EC-12
        await env.reconciler.task
        res = (await c.get("/reconcile/results")).json()["items"][0]
        assert res["state"] == "complete" and res["kind"] == "on_demand"
        assert (await c.get(f"/reconcile/results/{res['id']}")).json()["id"] == res["id"]
        assert (await c.get(f"/reconcile/results/{res['id']}/gaps?level=2")).json() == {"total": 0, "items": []}
        assert (await c.get(f"/reconcile/results/{res['id']}/gaps?level=7")).status_code == 422
        r = await c.post("/reconcile/full-rehash")
        assert r.status_code == 202 and r.json()["mode"] == "full_rehash"
        await env.reconciler.task
        h = (await c.get("/health")).json()
        assert h["status"] == "healthy", h


async def test_progress_50000_sources(env):  # AK-20
    async with env.pool.acquire() as con:
        await con.execute(
            "INSERT INTO alice.sources (id, kind, hash, title, path, blob) "
            "SELECT lpad(to_hex(g), 12, '0'), 'document', 'sha256:' || g, 'Dok ' || g, "
            "'documents/2026/11/' || g || '.md', 'x' FROM generate_series(1, 50000) g")
        await con.execute(
            "INSERT INTO alice.source_stages (source_id, stage, state) SELECT s.id, p.name, "
            "CASE WHEN p.name IN ('rag', 'wiki', 'thumbnail') THEN 'pending' ELSE 'done' END "
            "FROM alice.sources s CROSS JOIN alice.pipeline_stages p")
    calls = []

    def count(request):
        calls.append(request.url.path)
        return httpx.Response(503, json={"reasons": ["test"]})

    # register / detection must not be asked for progress: both are replaced by a counting fake
    fake = httpx.AsyncClient(transport=httpx.MockTransport(count), base_url="http://fake")
    env.rebuilds.registry = RegistryClient("http://fake", 5, client=fake)
    env.reconciler.registry = env.rebuilds.registry
    env.reconciler.detection = DetectionClient("http://fake", 5, client=fake)
    p = await env.rebuilds.start("classify", "document", "admin")
    assert p["in_run"] == 50000
    async with _client(env) as c:
        stop = False

        async def ticker():
            while not stop:
                await env.rebuilds.tick()
                await asyncio.sleep(1)

        bg = asyncio.create_task(ticker())
        await asyncio.sleep(0.1)
        before = len(calls)
        durations, ages = [], []
        t_end = time.monotonic() + 5
        while time.monotonic() < t_end:
            t0 = time.monotonic()
            r = await c.get(f"/rebuilds/{p['id']}")
            durations.append(time.monotonic() - t0)
            body = r.json()
            assert r.status_code == 200 and body["in_run"] == 50000
            ages.append(time.time() - __import__("datetime").datetime.fromisoformat(body["as_of"]).timestamp())
            await asyncio.sleep(0.05)  # 20 requests per second
        stop = True
        await bg
    assert len(durations) >= 80
    assert max(durations) < 0.2, max(durations)
    assert max(ages) <= 5, max(ages)
    # only the register health check of the run loop, no progress call reaches register or detection
    assert all(path == "/health" for path in calls[before:])
    await fake.aclose()
