"""Overview matrix, source list, errors and detail (AK-5–12, EC-4, EC-5, EC-10)."""
from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


async def test_matrix_counts_kind_and_deleted(env):
    await env.source(1, states={"extract": "failed"})
    await env.source(2, states={"classify": "failed_permanent"})
    await env.source(3, kind="image", states={"extract": "pending", "classify": "pending"})
    await env.source(4, deleted=True, states={"extract": "failed_permanent"})
    await env.source(5, kind="audio", states={s: "skipped" for s in ("extract", "classify", "database", "rag",
                                                                         "wiki", "thumbnail")})
    st = (await env.get("/etl/state")).json()
    assert st["stages"] == ["detect", "extract", "classify", "database", "rag", "wiki", "thumbnail"]
    m = st["matrix"]
    assert m["extract"] == {"pending": 1, "running": 0, "done": 1, "failed": 1, "failed_permanent": 0, "skipped": 1}
    assert m["classify"]["failed_permanent"] == 1 and m["detect"]["done"] == 4  # deleted not counted (AK-5)
    m = (await env.get("/etl/state", kind="document")).json()["matrix"]
    assert m["detect"]["done"] == 2 and m["extract"]["pending"] == 0  # AK-6
    m = (await env.get("/etl/state", kind="document", include_deleted="true")).json()["matrix"]
    assert m["detect"]["done"] == 3 and m["extract"]["failed_permanent"] == 1
    m = (await env.get("/etl/state", kind="video")).json()["matrix"]  # EC-10
    assert all(v == 0 for row in m.values() for v in row.values())


async def test_new_stage_appears_in_position(env):
    """AK-7: a stage added to the register shows up as a row at its position."""
    await env.source(1)
    await env.execute("INSERT INTO alice.pipeline_stages (name, position) VALUES ('ocrfix', 25)")
    try:
        st = (await env.get("/etl/state")).json()
        assert st["stages"][:4] == ["detect", "extract", "ocrfix", "classify"]
        assert sum(st["matrix"]["ocrfix"].values()) == 0
    finally:
        await env.execute("DELETE FROM alice.pipeline_stages WHERE name = 'ocrfix'")


async def test_list_of_a_cell(env):
    """AK-8: exactly the 3 sources with classify = failed_permanent, with all columns."""
    ids = [await env.source(i, states={"classify": "failed_permanent"}, attempts=5, error="LLM antwortet nicht " * 40)
           for i in range(1, 4)]
    await env.source(4, states={"classify": "failed"})
    await env.source(5, deleted=True, states={"classify": "failed_permanent"})
    r = (await env.get("/etl/sources", stage="classify", state="failed_permanent")).json()
    assert r["total"] == 3 and r["retryable"] == 3
    assert sorted(i["id"] for i in r["items"]) == ids
    it = r["items"][0]
    for k in ("title", "kind", "state", "attempts", "error", "last_attempt_at", "next_retry_at"):
        assert k in it
    assert it["attempts"] == 5 and len(it["error"]) == 300 and it["error_truncated"]  # EC-4
    r = (await env.get("/etl/sources", stage="classify", state="failed_permanent", deleted="all")).json()
    assert r["total"] == 4 and r["retryable"] == 3


async def test_list_paging_120(env):
    """AK-9: 120 sources in a cell, all reachable over the pages."""
    async with env.pool.acquire() as con:
        await con.execute(
            "INSERT INTO alice.sources (id, kind, hash, title, path) SELECT 'p' || lpad(g::text, 11, '0'), "
            "'document', 'sha256:p' || g, 'Seite ' || g, 'documents/p' || g || '.md' FROM generate_series(1, 120) g")
        await con.execute("INSERT INTO alice.source_stages (source_id, stage, state) SELECT id, 'extract', 'pending' "
                          "FROM alice.sources WHERE id LIKE 'p%'")
    seen = []
    for off in range(0, 150, 50):
        r = (await env.get("/etl/sources", stage="extract", state="pending", limit=50, offset=off)).json()
        assert r["total"] == 120
        seen += [i["id"] for i in r["items"]]
    assert len(seen) == 120 and len(set(seen)) == 120


async def test_search_title_and_id(env):
    """AK-10 + EC-5: search by part of the title (wildcards literal) or by id."""
    a = await env.source(1, title="Stromrechnung 100% <script>alert(1)</script>")
    b = await env.source(2, title="Kaufvertrag_Auto")
    await env.source(3, title="Anderes")
    r = (await env.get("/etl/sources", stage="detect", q="stromrech")).json()
    assert [i["id"] for i in r["items"]] == [a] and r["items"][0]["title"].endswith("</script>")
    assert [i["id"] for i in (await env.get("/etl/sources", stage="detect", q="100%")).json()["items"]] == [a]
    assert [i["id"] for i in (await env.get("/etl/sources", stage="detect", q="g_A")).json()["items"]] == [b]
    assert [i["id"] for i in (await env.get("/etl/sources", stage="detect", q=b.upper())).json()["items"]] == [b]
    assert (await env.get("/etl/sources", stage="detect", q="%")).json()["total"] == 1


async def test_list_filters_locked_and_kind(env):
    a = await env.source(1, locked="Frontmatter: YAML ungültig")
    await env.source(2)
    b = await env.source(3, kind="image")
    assert [i["id"] for i in (await env.get("/etl/sources", stage="detect", locked="yes")).json()["items"]] == [a]
    assert (await env.get("/etl/sources", stage="detect", locked="no")).json()["total"] == 2
    assert [i["id"] for i in (await env.get("/etl/sources", stage="detect", kind="image")).json()["items"]] == [b]
    assert (await env.get("/etl/sources", stage="nope!")).status_code == 422


async def test_errors_area(env):
    """AK-11: failed extract, failed_permanent classify and a locked source; newest first; filters."""
    a = await env.source(1, states={"extract": "failed"}, at=T0)
    b = await env.source(2, states={"classify": "failed_permanent"}, at=T0 + timedelta(hours=1))
    c = await env.source(3, locked="Frontmatter: kind geändert", at=T0 + timedelta(hours=2))
    await env.source(4, deleted=True, states={"extract": "failed"})
    await env.source(5, kind="image", states={"extract": "failed"}, at=T0 - timedelta(hours=1))
    r = (await env.get("/etl/errors")).json()
    assert [(i["id"], i["stage"], i["state"]) for i in r["items"]][:3] == [
        (c, None, "locked"), (b, "classify", "failed_permanent"), (a, "extract", "failed")]
    assert r["total"] == 4 and r["retryable"] == 3
    assert r["items"][0]["error"] == "Frontmatter: kind geändert"
    assert [i["id"] for i in (await env.get("/etl/errors", stage="extract", kind="document")).json()["items"]] == [a]
    assert [i["id"] for i in (await env.get("/etl/errors", state="failed_permanent")).json()["items"]] == [b]
    assert [i["id"] for i in (await env.get("/etl/errors", state="locked")).json()["items"]] == [c]
    assert (await env.get("/etl/errors", kind="image")).json()["total"] == 1


async def test_detail(env):
    """AK-12 + EC-4: base data, stages with the full message, both locations, events newest first."""
    long_error = "Traceback (most recent call last):\n" + "  File x\n" * 800
    sid = await env.source(1, states={"classify": "failed_permanent"}, attempts=5, error=long_error)
    await env.execute("INSERT INTO alice.source_locations (source_id, path, present) VALUES ($1, '/nas/a.pdf', TRUE)", sid)
    await env.execute("INSERT INTO alice.source_locations (source_id, path, present, gone_at) "
                      "VALUES ($1, '/nas/old/a.pdf', FALSE, NOW())", sid)
    await env.execute("INSERT INTO alice.source_events (source_id, event, message, created_at) VALUES "
                      "($1, 'hand_correction', 'erstes', NOW() - interval '1 hour'), ($1, 'file_moved', 'zweites', NOW())",
                      sid)
    await env.execute("INSERT INTO alice.doc_documents (id, type, markdown_path) VALUES ($1, 'Invoice', 'x.md')", sid)
    d = (await env.get(f"/etl/sources/{sid}")).json()
    assert d["id"] == sid and d["title"] == "Dokument 1" and d["kind"] == "document" and d["type"] == "Invoice"
    assert d["hash"].startswith("sha256:") and d["deleted"] is False and d["locked"] is False
    assert d["path"] == f"documents/2026/11/{sid}.md"
    cl = next(s for s in d["stages"] if s["stage"] == "classify")
    assert cl["error"] == long_error and cl["attempts"] == 5 and cl["retryable"] is True
    assert [s["stage"] for s in d["stages"]][:3] == ["detect", "extract", "classify"]
    assert not any(s["retryable"] for s in d["stages"] if s["stage"] != "classify")
    assert [(l["path"], l["present"]) for l in d["locations"]] == [("/nas/a.pdf", True), ("/nas/old/a.pdf", False)]
    assert [e["message"] for e in d["events"]] == ["zweites", "erstes"]
    assert (await env.get("/etl/sources/zzzzzzzzzzzz")).status_code == 404
    assert (await env.get("/etl/sources/..%2Fx")).status_code == 404


async def test_detail_locked_and_deleted_not_retryable(env):
    """AK-15 / EC-3."""
    a = await env.source(1, locked="YAML ungültig", states={"classify": "failed_permanent"})
    b = await env.source(2, deleted=True, states={"classify": "failed"})
    for sid in (a, b):
        d = (await env.get(f"/etl/sources/{sid}")).json()
        assert not any(s["retryable"] for s in d["stages"])
    assert (await env.get(f"/etl/sources/{a}")).json()["repo_error"] == "YAML ungültig"


async def test_counts_for_tile(env):
    """AK-36: 4 failed_permanent + 1 locked = 5, 7 failed (retry planned)."""
    n = 0
    for _ in range(4):
        n += 1
        await env.source(n, states={"classify": "failed_permanent"})
    n += 1
    await env.source(n, locked="kaputt")
    for _ in range(7):
        n += 1
        await env.source(n, states={"extract": "failed"})
    n += 1
    await env.source(n, deleted=True, states={"extract": "failed_permanent"})
    c = (await env.get("/etl/state")).json()["counts"]
    assert c["serious"] == 5 and c["failed"] == 7 and c["locked"] == 1 and c["failed_permanent"] == 4
