"""AK-46: 60,000 sources × 7 stages, state + one page of the source/error list each < 1 s."""
import time


async def test_60000_sources(env):
    async with env.pool.acquire() as con:
        await con.execute(
            "INSERT INTO alice.sources (id, kind, hash, title, path, deleted, repo_error) "
            "SELECT 'z' || lpad(g::text, 11, '0'), (ARRAY['document','image','email','audio','video'])[1 + g % 5], "
            "'sha256:z' || g, 'Quelle ' || g, 'x/z' || g || '.md', g % 97 = 0, "
            "CASE WHEN g % 1009 = 0 THEN 'kaputt' END FROM generate_series(1, 60000) g")
        await con.execute(
            "INSERT INTO alice.source_stages (source_id, stage, state, attempts, last_error, last_attempt_at) "
            "SELECT s.id, ps.name, (ARRAY['done','done','done','pending','failed','failed_permanent','skipped',"
            "'running'])[1 + (hashtext(s.id || ps.name) & 7)], 1, 'Fehler', NOW() - (random() * interval '30 days') "
            "FROM alice.sources s CROSS JOIN alice.pipeline_stages ps")
        await con.execute("ANALYZE alice.sources; ANALYZE alice.source_stages")
    timings = {}
    for name, path, params in (
            ("state", "/etl/state", {}),
            ("state kind", "/etl/state", {"kind": "document", "include_deleted": "true"}),
            ("list", "/etl/sources", {"stage": "classify", "state": "failed"}),
            ("list search", "/etl/sources", {"stage": "classify", "q": "Quelle 4711"}),
            ("list page 50", "/etl/sources", {"stage": "extract", "offset": 2500}),
            ("errors", "/etl/errors", {}),
            ("errors filtered", "/etl/errors", {"stage": "rag", "state": "failed_permanent", "kind": "email"})):
        await env.get(path, **params)  # warm
        t = time.perf_counter()
        r = await env.get(path, **params)
        timings[name] = time.perf_counter() - t
        assert r.status_code == 200, r.text
    print(timings)
    assert all(v < 1.0 for v in timings.values()), timings
