"""Rebuild runs end to end: real register in-process, simulated stage services (PROJ-120 AK-1–22)."""
import logging

import pytest

from app.rebuild import Invalid, Rebuilds, Rejected

from .conftest import git


async def _start(env, stage="classify", kind=None, by="admin"):
    return await env.rebuilds.start(stage, kind, by)


async def test_rebuild_from_classify(env):  # AK-1
    ids = await env.add(10)
    env.version = 2
    p = await _start(env)
    assert p["in_run"] == 10 and p["status"] == "running"
    assert p["scope"]["document"]["stages"] == ["classify", "database"]
    assert p["scope"]["document"]["not_served"] == ["rag", "wiki", "thumbnail"]
    env.claimed.clear()
    p = await env.drive(p["id"])
    assert p["status"] == "done" and p["finished"] == 10
    assert sorted(env.claimed["classify"]) == sorted(ids) and sorted(env.claimed["database"]) == sorted(ids)
    assert "extract" not in env.claimed
    for sid in ids:
        assert (await env.stage(sid, "extract"))["state"] == "done"
        assert (await env.reg.read_document(sid))["frontmatter"]["summary"] == "Zusammenfassung 2"


async def test_kind_filter(env):  # AK-2
    docs = await env.add(3)
    imgs = await env.add(2, kind="image")
    p = await _start(env, "extract", "document")
    assert p["total"] == 3 and p["in_run"] == 3
    await env.drive(p["id"])
    for sid in imgs:
        st = (await env.reg.get_source(sid))["stages"]
        assert all(s["state"] in ("pending", "done", "skipped") and s["attempts"] == 0 for s in st.values())
        assert st["detect"]["state"] == "done"
    assert len(docs) == 3


async def test_new_served_stage_joins_scope(env):  # AK-3
    await env.add(2)
    await env.reg.add_stage(name="summary2", position=45, skip_kinds=["audio", "video"],
                            resets_on_content_change=False)
    p = await _start(env, "database", "document")
    assert p["scope"]["document"]["stages"] == ["database"]
    assert "summary2" in p["scope"]["document"]["not_served"]
    await env.drive(p["id"])
    # the service of the new stage takes over work once → served → part of the next rebuild
    items = (await env.reg.claim("summary2", 10, ["document"]))["items"]
    for it in items:
        await env.reg.complete(it["source_id"], "summary2", it["token"])
    p = await _start(env, "database", "document")
    assert p["scope"]["document"]["stages"] == ["database", "summary2"]


async def test_failed_permanent_restarts_at_zero(env):  # AK-4
    sid = (await env.add(1))[0]
    await env.execute("UPDATE alice.source_stages SET state = 'failed_permanent', attempts = 5, last_error = 'x' "
                      "WHERE source_id = $1 AND stage = 'classify'", sid)
    p = await _start(env)
    await env.rebuilds.tick()
    st = await env.stage(sid, "classify")
    assert (st["state"], st["attempts"]) == ("pending", 0)
    assert (await env.drive(p["id"]))["status"] == "done"


async def test_exclusions_counted(env, tmp_path):  # AK-5
    ok = await env.add(2)
    gone = (await env.add(1))[0]
    await env.reg.remove_location(gone, {"path": (await env.reg.get_source(gone))["locations"][0]["path"]})
    locked = (await env.add(1))[0]
    path = env.repo / (await env.reg.get_source(locked))["path"]
    path.write_text(path.read_text().replace("kind: document", "kind: [broken"))
    await env.reg.scan()
    audio = (await env.add(1, kind="audio"))[0]
    image = (await env.add(1, kind="image"))[0]
    await env.work_all()  # normal work (database removes the deleted one, PROJ-119)
    before = {s: (await env.reg.get_source(s))["stages"] for s in (gone, locked, audio, image)}
    p = await _start(env, "extract")
    assert p["total"] == 6 and p["in_run"] == 2
    assert p["excluded"] == {"deleted": 1, "locked": 1, "skipped": 1, "not_served": 1}
    await env.drive(p["id"])
    after = {s: (await env.reg.get_source(s))["stages"] for s in (gone, locked, audio, image)}
    strip = lambda d: {k: (v["state"], v["attempts"]) for k, v in d.items()}  # noqa: E731
    assert {s: strip(v) for s, v in after.items()} == {s: strip(v) for s, v in before.items()}
    assert len(ok) == 2


async def test_snapshot_new_source_not_in_run(env):  # AK-6
    await env.add(3)
    p = await _start(env)
    await env.rebuilds.tick()
    new = (await env.add(1, done=()))[0]
    p2 = await env.drive(p["id"])
    assert p2["total"] == 3
    assert (await env.stage(new, "database"))["state"] == "done"  # processed normally


async def test_only_one_run(env):  # AK-7
    await env.add(1)
    p = await _start(env)
    with pytest.raises(Rejected) as exc:
        await _start(env, "extract")
    assert exc.value.run["id"] == p["id"]
    await env.rebuilds.control(p["id"], "pause")
    with pytest.raises(Rejected):
        await _start(env)
    await env.rebuilds.control(p["id"], "cancel")
    await env.drive(p["id"])
    assert (await _start(env))["status"] == "running"


async def test_invalid_start_stage(env):
    with pytest.raises(Invalid):
        await _start(env, "detect")
    with pytest.raises(Invalid):
        await _start(env, "nope")


async def test_manual_value_survives(env):  # AK-8
    sid = (await env.add(1))[0]
    path = env.repo / (await env.reg.get_source(sid))["path"]
    fm, content = env.md.parse(path.read_text())
    fm["summary"] = "Von Hand"
    path.write_text(env.md.render(fm, content))
    await env.reg.scan()
    await env.work_all()
    env.version = 3
    p = await _start(env, "extract")
    await env.drive(p["id"])
    fm = (await env.reg.read_document(sid))["frontmatter"]
    assert fm["summary"] == "Von Hand" and "summary" in fm["manual"]
    assert (await env.fetchval("SELECT summary FROM alice.doc_documents WHERE id = $1", sid)) == "Von Hand"


async def test_batch_commits(env):  # AK-9
    ids = await env.add(1200, done=())
    await env.work_all(limit=5000)
    await env.reg.flush_due(force=True)
    before = len(git(env.repo, "log", "--format=%s").splitlines())
    env.version = 2
    p = await _start(env, "extract")
    await env.drive(p["id"], rounds=50)
    await env.reg.flush_due(force=True)
    log = git(env.repo, "log", "--format=%s").splitlines()
    subjects = log[:len(log) - before]
    assert subjects and all(s.startswith("rebuild: ") for s in subjects), subjects[:5]
    assert len(subjects) < 1200
    files = [len([f for f in git(env.repo, "show", "--name-only", "--format=", f"HEAD~{i}").splitlines() if f])
             for i in range(len(subjects))]
    assert max(files) <= 500
    assert len(ids) == 1200


async def test_throttle(env, settings):  # AK-10
    await env.add(500, done=("extract",))
    await env.work_all()
    settings.stage_limit = 20
    p = await _start(env, "extract")
    rid = p["id"]

    async def check():
        rows = await env.fetch(
            "SELECT ss.stage, count(*) AS n FROM alice.rebuild_items i JOIN alice.source_stages ss "
            "ON ss.source_id = i.source_id WHERE i.run_id = $1 AND ss.rebuild_run = $1 "
            "AND ss.state IN ('pending', 'running') GROUP BY ss.stage", rid)
        assert all(r["n"] <= 20 for r in rows), [dict(r) for r in rows]

    p = await env.drive(rid, rounds=400, check=check, limit=7)
    assert p["status"] == "done" and p["finished"] == 500


async def test_pause_resume(env):  # AK-13, AK-14
    await env.add(30)
    env.settings.stage_limit = 5
    p = await _start(env)
    await env.rebuilds.tick()
    await env.rebuilds.control(p["id"], "pause")
    released = (await env.rebuilds.progress(p["id"]))["released"]
    for _ in range(3):
        await env.work_all()
        await env.rebuilds.tick()
    q = await env.rebuilds.progress(p["id"])
    assert q["status"] == "paused" and q["released"] == released == 5
    assert q["stages"]["classify"]["done"] == 5  # released ones ran to the end
    env.claimed.clear()
    await env.rebuilds.control(p["id"], "resume")
    q = await env.drive(p["id"])
    assert q["status"] == "done" and q["finished"] == 30 and q["stages"]["classify"]["done"] == 30
    assert len(env.claimed["classify"]) == 25 == len(set(env.claimed["classify"]))  # nothing twice


async def test_cancel(env):  # AK-15
    ids = await env.add(50)
    env.settings.stage_limit = 10
    p = await _start(env)
    await env.rebuilds.tick()
    await env.rebuilds.control(p["id"], "cancel")
    q = await env.drive(p["id"])
    assert q["status"] == "cancelled" and q["released"] == 10 and q["finished"] == 10
    untouched = await env.fetch("SELECT i.source_id FROM alice.rebuild_items i WHERE i.run_id = $1 "
                                "AND i.released_at IS NULL", p["id"])
    assert len(untouched) == 40
    for r in untouched:
        st = await env.stage(r["source_id"], "classify")
        assert st["state"] == "done"
    assert (await env.rebuilds.progress(p["id"]))["status"] == "cancelled"
    assert await env.fetchval("SELECT reconcile_id FROM alice.rebuild_runs WHERE id = $1", p["id"]) is None
    assert len(ids) == 50


@pytest.mark.parametrize("paused", [False, True])
async def test_restart(env, paused):  # AK-16
    await env.add(20)
    env.settings.stage_limit = 5
    p = await _start(env)
    await env.rebuilds.tick()
    if paused:
        await env.rebuilds.control(p["id"], "pause")
    env.rebuilds = Rebuilds(env.settings, env.pool, env.registry)  # restart: state from PostgreSQL
    await env.rebuilds.tick()
    q = await env.rebuilds.progress(p["id"])
    assert q["status"] == ("paused" if paused else "running") and q["released"] == 5
    if paused:
        await env.rebuilds.control(p["id"], "resume")
    env.claimed.clear()
    q = await env.drive(p["id"])
    assert q["status"] == "done" and len(env.claimed["classify"]) == len(set(env.claimed["classify"]))


async def test_progress_fields_and_errors(env):  # AK-18, AK-19, EC-5
    ids = await env.add(97)
    gone = await env.add(3)
    for sid in gone:
        await env.reg.remove_location(sid, {"path": (await env.reg.get_source(sid))["locations"][0]["path"]})
    p = await _start(env, by="Andrea")
    assert (p["total"], p["excluded_total"], p["excluded"], p["in_run"]) == (100, 3, {"deleted": 3}, 97)
    assert p["started_by"] == "Andrea" and p["start_stage"] == "classify" and p["started_at"] and p["as_of"]
    await env.rebuilds.tick()
    await env.work("classify", fail={ids[0]: True, ids[1]: False})
    await env.rebuilds.tick()
    p = await env.rebuilds.progress(p["id"])
    for st in ("classify", "database"):
        v = p["stages"][st]
        assert v["done"] + v["failed"] + v["running"] + v["open"] == 97 == v["sources"]
    assert p["stages"]["classify"]["failed"] == 2
    assert p["throughput_per_hour"] >= 0 and "remaining_seconds" in p
    errs = await env.rebuilds.errors(p["id"], 100, 0)
    assert errs["total"] == 2
    assert {(e["id"], e["stage"], e["error"]) for e in errs["items"]} == {
        (ids[0], "classify", "Fehler in classify"), (ids[1], "classify", "Fehler in classify")}
    assert all(e["title"] for e in errs["items"])
    # failed (backoff) keeps the run running (EC-5); permanent + blocked database counts as through
    for _ in range(3):
        await env.work_all()
        await env.rebuilds.tick()
    q = await env.rebuilds.progress(p["id"])
    assert q["status"] == "running" and q["finished"] == 96
    await env.execute("UPDATE alice.source_stages SET state = 'failed_permanent' WHERE source_id = $1 "
                      "AND stage = 'classify'", ids[1])
    q = await env.drive(p["id"])
    assert q["status"] == "done" and q["stages"]["database"]["failed"] == 2


async def test_log_lines(env, caplog):  # AK-21
    await env.add(5)
    env.settings.log_interval_seconds = 60
    now = [1000.0]
    env.rebuilds.clock = lambda: now[0]
    caplog.set_level(logging.INFO, logger="alice-etl-rebuild")
    p = await _start(env)
    for _ in range(3):
        now[0] += 61
        await env.rebuilds.tick()
    await env.rebuilds.control(p["id"], "pause")
    await env.rebuilds.control(p["id"], "resume")
    await env.drive(p["id"])
    text = caplog.text
    assert text.count("progress (") >= 3
    for needle in ("started by admin", "paused", "resumed", "finished"):
        assert needle in text, needle
    p2 = await _start(env)
    await env.rebuilds.control(p2["id"], "cancel")
    assert "cancelled" in caplog.text


async def test_list_of_runs(env):  # AK-22
    await env.add(2)
    a = await _start(env)
    await env.drive(a["id"])
    b = await _start(env, "database")
    await env.rebuilds.control(b["id"], "cancel")
    await env.drive(b["id"])
    out = await env.rebuilds.list_runs(20, 0)
    assert out["total"] == 2
    got = {r["id"]: r for r in out["items"]}
    assert got[a["id"]]["status"] == "done" and got[b["id"]]["status"] == "cancelled"
    for r in got.values():
        assert r["start_stage"] and r["started_at"] and r["finished_at"] and r["in_run"] == 2 and "stages" in r


async def test_deleted_during_run_and_empty_run(env):  # EC-1, EC-4
    ids = await env.add(3)
    env.settings.stage_limit = 1
    p = await _start(env)
    await env.reg.remove_location(ids[2], {"path": (await env.reg.get_source(ids[2]))["locations"][0]["path"]})
    q = await env.drive(p["id"])
    assert q["status"] == "done" and q["excluded"] == {"deleted": 1} and q["in_run"] == 2
    e = await _start(env, "extract", "email")
    assert e["total"] == 0
    assert (await env.drive(e["id"]))["status"] == "done"


async def test_waits_while_register_unavailable(env, monkeypatch):  # AK-40
    await env.add(5)
    env.settings.stage_limit = 2
    p = await _start(env)
    env.reg._set_available(False, "Repo-Ordner nicht erreichbar")
    monkeypatch.setattr(env.reg, "check_repo", lambda: _noop())
    await env.rebuilds.tick()
    q = await env.rebuilds.progress(p["id"])
    assert q["status"] == "waiting" and "Repo" in q["reason"] and q["released"] == 0
    env.reg._set_available(True)
    q = await env.drive(p["id"])
    assert q["status"] == "done"


async def _noop():
    return None


async def test_stage_service_down(env):  # EC-13
    await env.add(3)
    p = await _start(env)
    for _ in range(3):
        await env.rebuilds.tick()
    q = await env.rebuilds.progress(p["id"])
    assert q["status"] == "running" and q["stages"]["classify"]["open"] == 3
    assert q["throughput_per_hour"] == 0 and q["remaining_seconds"] is None
