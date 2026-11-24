"""Interface extensions for rebuild + reconciliation (PROJ-120): release of rebuild portions with the
run flag, normal work before rebuild work, batch commits for rebuild writes, served stages, level 2
(register <-> repo) check and repairs."""
from app import markdown as md

from .conftest import git
from .test_registry import _done, claim_one, log, register, stages

PATH = "/nas/scanner/scan_0042.pdf"


def h(n: int) -> str:
    return f"sha256:{n:016d}"


async def _sources(reg, n, start=0):
    return [(await register(reg, h=h(start + i), title=f"doc{start + i}.pdf", path=f"/nas/d/{start + i}.pdf"))["id"]
            for i in range(n)]


async def _row(pool, sid, stage):
    async with pool.acquire() as con:
        return await con.fetchrow("SELECT state, attempts, rebuild_run, last_error FROM alice.source_stages "
                                  "WHERE source_id = $1 AND stage = $2", sid, stage)


async def test_release_flags_and_resets_attempts(reg, pool):  # AK-4
    sid = (await register(reg))["id"]
    await _done(reg, sid, "extract")
    async with pool.acquire() as con:
        await con.execute("UPDATE alice.source_stages SET state = 'failed_permanent', attempts = 5, "
                          "last_error = 'x' WHERE source_id = $1 AND stage = 'classify'", sid)
    out = await reg.release_rebuild(7, [{"id": sid, "stages": ["classify", "database"]}])
    assert out["released"] == [sid]
    row = await _row(pool, sid, "classify")
    assert (row["state"], row["attempts"], row["rebuild_run"], row["last_error"]) == ("pending", 0, 7, None)
    assert (await _row(pool, sid, "extract"))["state"] == "done"  # not in the portion


async def test_release_is_idempotent_and_skips_running(reg, pool):  # AK-16 (no double release)
    a, b = await _sources(reg, 2)
    await _done(reg, a, "extract")
    await reg.release_rebuild(1, [{"id": a, "stages": ["extract"]}])
    tok = await claim_one(reg, "extract", a)
    await reg.complete(a, "extract", tok)
    await reg.release_rebuild(1, [{"id": a, "stages": ["extract"]}])  # same run again: no reset
    assert (await _row(pool, a, "extract"))["state"] == "done"
    tok_b = await claim_one(reg, "extract", b)  # running normal work stays untouched
    await reg.release_rebuild(2, [{"id": b, "stages": ["extract"]}])
    row = await _row(pool, b, "extract")
    assert row["state"] == "running" and row["rebuild_run"] is None
    await reg.complete(b, "extract", tok_b)


async def test_release_reports_deleted_and_locked(reg, pool, repo_dir):  # EC-1
    gone, locked, ok = await _sources(reg, 3)
    await reg.remove_location(gone, {"path": "/nas/d/0.pdf"})
    path = repo_dir / (await reg.get_source(locked))["path"]
    path.write_text(path.read_text().replace("kind: document", "kind: [broken"))
    await reg.scan()
    out = await reg.release_rebuild(3, [{"id": s, "stages": ["extract"]} for s in (gone, locked, ok)]
                                    + [{"id": "zzzzzzzzzzzz", "stages": ["extract"]}])
    assert out == {"released": [ok], "deleted": [gone], "locked": [locked], "unknown": ["zzzzzzzzzzzz"]}
    assert (await _row(pool, gone, "extract"))["rebuild_run"] is None


async def test_normal_work_before_rebuild_work(make_registry, pool):  # AK-11
    reg = await make_registry(redis=None)
    old = await _sources(reg, 3)
    for sid in old:
        await _done(reg, sid, "extract")
    await reg.release_rebuild(1, [{"id": s, "stages": ["extract"]} for s in old])
    new = (await register(reg, h=h(99), title="new.pdf", path="/nas/new.pdf"))["id"]
    for args in ((), (["document"],)):  # plain claim and claim with kinds
        items = (await reg.claim("extract", 1, *args))["items"]
        assert [i["source_id"] for i in items] == [new]
        await reg.release(new, "extract", items[0]["token"])
    items = (await reg.claim("extract", 10, ["document"]))["items"]
    assert [i["source_id"] for i in items][0] == new and len(items) == 4


async def test_redis_claim_fills_with_rebuild_work(reg, pool, fake_redis):  # AK-11 with the Redis queue
    old = await _sources(reg, 2)
    for sid in old:
        await _done(reg, sid, "extract")
    await reg.resync_queue()
    await reg.release_rebuild(1, [{"id": s, "stages": ["extract"]} for s in old])
    assert not fake_redis.z.get("sot:queue:extract")  # rebuild work never enters the queue
    await reg.resync_queue()
    assert not fake_redis.z.get("sot:queue:extract")
    new = (await register(reg, h=h(99), title="new.pdf", path="/nas/new.pdf"))["id"]
    items = (await reg.claim("extract", 3))["items"]
    assert items[0]["source_id"] == new and {i["source_id"] for i in items[1:]} == set(old)


async def test_rebuild_writes_go_into_batch_commits(make_registry, repo_dir):  # AK-9
    reg = await make_registry(batch_max_files=500)
    ids = await _sources(reg, 3)
    for sid in ids:
        await _done(reg, sid, "extract")
    await reg.release_rebuild(4, [{"id": s, "stages": ["extract"]} for s in ids])
    before = len(log(repo_dir))
    for sid in ids:
        tok = await claim_one(reg, "extract", sid)
        await reg.write_document(sid, stage="extract", content="## Seite 1\n\nneu\n", token=tok)
        await reg.complete(sid, "extract", tok)
    assert len(log(repo_dir)) == before  # nothing committed yet: collected
    await reg.flush_due(force=True)
    subjects = log(repo_dir, fmt="%s")
    assert len(subjects) == before + 1 and subjects[0] == "rebuild: extract 3 sources"


async def test_normal_reset_clears_flag(reg, pool):  # EC-2: hand correction / retry has normal priority
    sid = (await register(reg))["id"]
    await _done(reg, sid, "extract")
    await reg.release_rebuild(1, [{"id": sid, "stages": ["extract", "classify"]}])
    await reg.retry(sid, "extract")
    assert (await _row(pool, sid, "extract"))["rebuild_run"] is None
    assert (await _row(pool, sid, "classify"))["rebuild_run"] == 1


async def test_served_stages_recorded(reg, pool):  # option A of #12
    async with pool.acquire() as con:
        await con.execute("DELETE FROM alice.pipeline_stage_served")
    reg.served.clear()
    doc = (await register(reg, complete=True))["id"]
    await register(reg, h=h(5), title="a.jpg", path="/nas/a.jpg", kind="image", complete=True)
    items = (await reg.claim("extract", 10, ["document"]))["items"]
    await reg.release(doc, "extract", items[0]["token"])
    async with pool.acquire() as con:
        rows = {(r["stage"], r["kind"]) for r in await con.fetch("SELECT stage, kind FROM alice.pipeline_stage_served")}
    assert rows == {("detect", "document"), ("detect", "image"), ("extract", "document")}


async def test_event_endpoint(reg):
    sid = (await register(reg))["id"]
    await reg.add_event(sid, "info", "reconcile_db_retry", "Abgleich: database erneut")
    assert (await reg.get_source(sid))["events"][0]["event"] == "reconcile_db_retry"


# ---------------------------------------------------------------- level 2
async def test_repo_check_consistent(reg):  # AK-32 (level 2)
    await _sources(reg, 3)
    out = await reg.repo_check()
    assert out["findings"] == [] and out["sources"] == 3


async def test_missing_markdown_restored_from_history(reg, repo_dir):  # AK-26 (git history)
    sid = (await register(reg))["id"]
    rel = (await reg.get_source(sid))["path"]
    (repo_dir / rel).unlink()
    git(repo_dir, "add", "-A")
    git(repo_dir, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "-m", "oops")
    findings = (await reg.repo_check())["findings"]
    assert findings == [{"gap": "markdown_missing", "id": sid, "path": rel, "action": "restore"}]
    out = await reg.repo_repair([{"id": sid, "action": "restore"}])
    assert out["results"][0]["repaired"] and out["results"][0]["how"] == "restored"
    assert (repo_dir / rel).exists()
    assert (await reg.get_source(sid))["events"][0]["event"] == "reconcile_restored"
    assert (await reg.repo_check())["findings"] == []
    await reg.scan()  # the restored file is not taken for a hand correction
    assert (await reg.get_source(sid))["events"][0]["event"] == "reconcile_restored"


async def test_missing_markdown_without_history_recreated(reg, repo_dir, pool):  # AK-26 (no history)
    sid = (await register(reg))["id"]
    await _done(reg, sid, "extract", "classify")
    rel = (await reg.get_source(sid))["path"]
    (repo_dir / rel).unlink()
    async with pool.acquire() as con:  # blob and path unknown to git (e.g. repo replaced)
        await con.execute("UPDATE alice.sources SET blob = $2, path = $3 WHERE id = $1", sid, "0" * 40,
                          rel.replace(".md", "-x.md"))
    out = await reg.repo_repair([{"id": sid, "action": "restore"}])
    assert out["results"][0]["how"] == "recreated"
    src = await reg.get_source(sid)
    assert (repo_dir / src["path"]).exists()
    fm, content = md.parse((repo_dir / src["path"]).read_text())
    assert fm["id"] == sid and PATH in content
    assert all(src["stages"][s]["state"] == "pending" for s in ("extract", "classify", "database"))
    assert src["events"][0]["event"] == "reconcile_recreated"


async def test_orphan_and_kind_mismatch_reported(reg, repo_dir):  # AK-27
    sid = (await register(reg))["id"]
    rel = (await reg.get_source(sid))["path"]
    text = (repo_dir / rel).read_text()
    (repo_dir / "documents" / "stray.md").write_text(text.replace(sid, "unknown00000"))
    (repo_dir / "images" / "copy.md").write_text(text.replace("kind: document", "kind: image"))
    before = {p: (repo_dir / p).read_text() for p in ("documents/stray.md", "images/copy.md")}
    findings = (await reg.repo_check())["findings"]
    assert sorted((f["gap"], f["path"]) for f in findings) == [
        ("markdown_orphan", "documents/stray.md"), ("markdown_orphan", "images/copy.md")]
    assert any("kind image" in f["detail"] for f in findings)
    assert all(f["action"] is None for f in findings)
    assert {p: (repo_dir / p).read_text() for p in before} == before


async def test_wrong_place_moved_with_history(reg, repo_dir, pool):  # AK-28
    sid = (await register(reg))["id"]
    rel = (await reg.get_source(sid))["path"]
    async with pool.acquire() as con:  # deleted, but markdown still outside deleted/
        await con.execute("UPDATE alice.sources SET deleted = TRUE, deleted_at = NOW() WHERE id = $1", sid)
    findings = (await reg.repo_check())["findings"]
    assert [(f["gap"], f["action"]) for f in findings] == [("wrong_place", "move")]
    out = await reg.repo_repair([{"id": sid, "action": "move"}])
    new = out["results"][0]["path"]
    assert new == "deleted/" + rel and (repo_dir / new).exists() and not (repo_dir / rel).exists()
    assert len(git(repo_dir, "log", "--follow", "--format=%s", "--", new).splitlines()) >= 2
    assert (await reg.get_source(sid))["events"][0]["event"] == "reconcile_moved"
    async with pool.acquire() as con:  # the other way round: active source below deleted/
        await con.execute("UPDATE alice.sources SET deleted = FALSE, deleted_at = NULL WHERE id = $1", sid)
    assert [f["gap"] for f in (await reg.repo_check())["findings"]] == ["wrong_place"]
    out = await reg.repo_repair([{"id": sid, "action": "move"}])
    assert out["results"][0]["path"] == rel


async def test_moved_markdown_put_back(reg, repo_dir):
    sid = (await register(reg))["id"]
    rel = (await reg.get_source(sid))["path"]
    (repo_dir / rel).rename(repo_dir / "documents" / "elsewhere.md")
    findings = (await reg.repo_check())["findings"]
    assert findings[0]["found_at"] == "documents/elsewhere.md"
    await reg.repo_repair([{"id": sid, "action": "restore", "found_at": "documents/elsewhere.md"}])
    assert (repo_dir / rel).exists() and not (repo_dir / "documents" / "elsewhere.md").exists()
    assert (await reg.repo_check())["findings"] == []


async def test_http_endpoints(reg):
    import httpx

    from app import main

    main.app.state.reg = reg
    sid = (await register(reg))["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://r") as c:
        r = await c.post("/rebuild/release", json={"run": 1, "items": [{"id": sid, "stages": ["extract"]}]})
        assert r.status_code == 200 and r.json()["released"] == [sid]
        assert (await c.post("/rebuild/release", json={"run": 1, "items": [{"id": "x", "stages": []}]})).status_code == 422
        assert (await c.get("/maintenance/repo-check")).json()["findings"] == []
        r = await c.post("/maintenance/repo-repair", json={"items": [{"id": sid, "action": "drop"}]})
        assert r.status_code == 422
        r = await c.post(f"/sources/{sid}/events", json={"event": "reconcile_x", "message": "m"})
        assert r.status_code == 200
    assert (await stages(reg, sid))["extract"]["state"] == "pending"
