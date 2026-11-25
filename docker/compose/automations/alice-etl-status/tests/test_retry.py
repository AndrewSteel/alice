"""Retry single and bulk through the real register (AK-13–19, EC-2)."""


async def _stage(env, sid, stage):
    return await env.fetch("SELECT state, attempts, last_error FROM alice.source_stages WHERE source_id = $1 "
                           "AND stage = $2", sid, stage)


async def test_single_failed_permanent(env):
    """AK-13: pending with counter 0, event with the admin's name."""
    sid = await env.source(1, states={"classify": "failed_permanent"}, attempts=5)
    r = await env.post(f"/etl/sources/{sid}/stages/classify/retry")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "pending" and r.json()["attempts"] == 0
    (row,) = await _stage(env, sid, "classify")
    assert row["state"] == "pending" and row["attempts"] == 0 and row["last_error"] is None
    ev = await env.fetch("SELECT event, message FROM alice.source_events WHERE source_id = $1", sid)
    assert len(ev) == 1 and ev[0]["event"] == "manual_retry" and "etl-admin" in ev[0]["message"]
    d = (await env.get(f"/etl/sources/{sid}")).json()
    assert next(s for s in d["stages"] if s["stage"] == "classify")["state"] == "pending"
    assert d["events"][0]["event"] == "manual_retry"


async def test_single_failed(env):
    """AK-14."""
    sid = await env.source(1, states={"extract": "failed"}, attempts=2)
    assert (await env.post(f"/etl/sources/{sid}/stages/extract/retry")).status_code == 200
    (row,) = await _stage(env, sid, "extract")
    assert row["state"] == "pending" and row["attempts"] == 0


async def test_not_offered_states_rejected(env):
    """AK-15/AK-19: done, pending, running, skipped, locked and deleted are rejected and unchanged."""
    sid = await env.source(1, states={"extract": "pending", "classify": "running", "rag": "skipped"}, attempts=1)
    for stage in ("detect", "extract", "classify", "rag"):
        before = await _stage(env, sid, stage)
        r = await env.post(f"/etl/sources/{sid}/stages/{stage}/retry")
        assert r.status_code == 409 and r.json()["error"] == "not_retryable" and r.json()["reason"] == "state"
        assert await _stage(env, sid, stage) == before
    locked = await env.source(2, locked="YAML ungültig", states={"classify": "failed_permanent"}, attempts=5)
    r = await env.post(f"/etl/sources/{locked}/stages/classify/retry")
    assert r.status_code == 409 and r.json()["reason"] == "locked"
    deleted = await env.source(3, deleted=True, states={"classify": "failed"}, attempts=1)
    r = await env.post(f"/etl/sources/{deleted}/stages/classify/retry")
    assert r.status_code == 409 and r.json()["reason"] == "deleted"
    assert (await _stage(env, locked, "classify"))[0]["state"] == "failed_permanent"
    assert (await _stage(env, deleted, "classify"))[0]["state"] == "failed"
    assert await env.fetchval("SELECT count(*) FROM alice.source_events") == 0
    assert (await env.post("/etl/sources/zzzzzzzzzzzz/stages/classify/retry")).status_code == 404


async def test_second_tab(env):
    """AK-19: second click after the stage is already pending changes nothing."""
    sid = await env.source(1, states={"classify": "failed_permanent"}, attempts=5)
    assert (await env.post(f"/etl/sources/{sid}/stages/classify/retry")).status_code == 200
    r = await env.post(f"/etl/sources/{sid}/stages/classify/retry")
    assert r.status_code == 409 and r.json()["state"] == "pending"
    assert await env.fetchval("SELECT count(*) FROM alice.source_events") == 1


async def test_bulk_30_of_40(env):
    """AK-16: dialog count 30, then exactly these 30 pending/0, nothing else changed."""
    fp = [await env.source(i, states={"classify": "failed_permanent", "extract": "failed"}, attempts=5)
          for i in range(1, 31)]
    for i in range(31, 41):
        await env.source(i, states={"classify": "pending"})
    other = await env.source(41, kind="image", states={"classify": "failed_permanent"}, attempts=5)
    before = {tuple(r) for r in await env.fetch(
        "SELECT source_id, stage, state, attempts FROM alice.source_stages WHERE NOT (source_id = ANY($1::text[]) "
        "AND stage = 'classify')", fp)}
    flt = {"stage": "classify", "kind": "document"}
    lst = (await env.get("/etl/sources", **flt)).json()
    assert lst["total"] == 40 and lst["retryable"] == 30
    dry = (await env.post("/etl/retry", json={"scope": "sources", "filter": flt, "dry_run": True})).json()
    assert dry == {"sources": 30, "limit": 1000, "allowed": True}
    assert await env.fetchval("SELECT count(*) FROM alice.source_stages WHERE state = 'pending' "
                              "AND stage = 'classify'") == 10  # dry run changed nothing (AK-17)
    r = (await env.post("/etl/retry", json={"scope": "sources", "filter": flt})).json()
    assert r["sources"] == 30 and r["stages"] == 30
    rows = await env.fetch("SELECT state, attempts FROM alice.source_stages WHERE source_id = ANY($1::text[]) "
                           "AND stage = 'classify'", fp)
    assert all(x["state"] == "pending" and x["attempts"] == 0 for x in rows)
    after = {tuple(r) for r in await env.fetch(
        "SELECT source_id, stage, state, attempts FROM alice.source_stages WHERE NOT (source_id = ANY($1::text[]) "
        "AND stage = 'classify')", fp)}
    assert after == before
    assert (await _stage(env, other, "classify"))[0]["state"] == "failed_permanent"
    assert await env.fetchval("SELECT count(*) FROM alice.source_events WHERE event = 'manual_retry'") == 30


async def test_bulk_errors_scope_skips_locked(env):
    a = await env.source(1, states={"extract": "failed", "classify": "failed_permanent"}, attempts=3)
    await env.source(2, locked="kaputt", states={"extract": "failed"})
    b = await env.source(3, states={"classify": "failed_permanent"}, attempts=5)
    dry = (await env.post("/etl/retry", json={"scope": "errors", "filter": {}, "dry_run": True})).json()
    assert dry["sources"] == 2
    r = (await env.post("/etl/retry", json={"scope": "errors", "filter": {}})).json()
    assert r["sources"] == 2 and r["stages"] == 3
    assert {x["state"] for x in await env.fetch("SELECT state FROM alice.source_stages WHERE source_id = ANY($1::text[]) "
                                               "AND stage IN ('extract', 'classify')", [a, b])} <= {"pending", "done"}
    assert (await env.post("/etl/retry", json={"scope": "errors", "filter": {"state": "locked"},
                                               "dry_run": True})).json()["sources"] == 0
    assert (await env.post("/etl/retry", json={"scope": "errors", "filter": {"state": "bogus"}})).status_code == 422


async def test_bulk_selection_changed_meanwhile(env):
    """EC-2: only stages still failed at execution; the answer names the real number."""
    ids = [await env.source(i, states={"classify": "failed_permanent"}, attempts=5) for i in range(1, 6)]
    flt = {"stage": "classify"}
    assert (await env.post("/etl/retry", json={"scope": "sources", "filter": flt, "dry_run": True})).json()["sources"] == 5
    await env.execute("UPDATE alice.source_stages SET state = 'done' WHERE source_id = ANY($1::text[]) "
                      "AND stage = 'classify'", ids[:2])
    r = (await env.post("/etl/retry", json={"scope": "sources", "filter": flt})).json()
    assert r["sources"] == 3
    assert await env.fetchval("SELECT count(*) FROM alice.source_stages WHERE stage = 'classify' AND state = 'done'") == 2


async def test_bulk_limit(env):
    """AK-18: 1,001 sources over the limit of 1,000 → rejected, nothing changed, also on direct call."""
    async with env.pool.acquire() as con:
        await con.execute(
            "INSERT INTO alice.sources (id, kind, hash, title, path) SELECT 'l' || lpad(g::text, 11, '0'), "
            "'document', 'sha256:l' || g, 'L ' || g, 'documents/l' || g || '.md' FROM generate_series(1, 1001) g")
        await con.execute("INSERT INTO alice.source_stages (source_id, stage, state, attempts) "
                          "SELECT id, 'classify', 'failed_permanent', 5 FROM alice.sources")
    flt = {"stage": "classify", "state": "failed_permanent"}
    dry = (await env.post("/etl/retry", json={"scope": "sources", "filter": flt, "dry_run": True})).json()
    assert dry == {"sources": 1001, "limit": 1000, "allowed": False}
    r = await env.post("/etl/retry", json={"scope": "sources", "filter": flt})
    assert r.status_code == 409 and r.json()["error"] == "limit_exceeded" and r.json()["count"] == 1001
    r = await env.post("/etl/retry", json={"scope": "errors", "filter": {}})
    assert r.status_code == 409
    assert await env.fetchval("SELECT count(*) FROM alice.source_stages WHERE state = 'failed_permanent'") == 1001
