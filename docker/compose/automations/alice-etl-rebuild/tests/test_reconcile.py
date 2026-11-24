"""Reconciliation end to end: register + detection in-process, temp folders as NAS (PROJ-120 AK-17, AK-23–43)."""
import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.clients import Unavailable
from app.reconcile import Busy409


def write(path, content: str, mtime=None):
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def sha(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


async def folder(env, name="docs"):
    path = str(env.nas / "share" / name)
    os.makedirs(path, exist_ok=True)
    await env.execute("INSERT INTO alice.dms_watched_folders (path, enabled) VALUES ($1, TRUE)", path)
    return path


async def nightly_detection(env):
    r = await env.det.start("night")
    assert r["state"] == "done", r


async def reconcile(env, kind="on_demand", mode="levels", run=None):
    rid = await env.reconciler.start(kind, mode, run)
    await env.reconciler.task
    return await env.reconciler.get_result(rid)


async def gaps(env, rid, level=None):
    return (await env.reconciler.gaps(rid, level, 1000, 0))["items"]


async def nas_sources(env, n, f=None):
    """n documents found by the detection, all stages done (consistent state)."""
    f = f or await folder(env)
    paths = [write(f"{f}/d{i}.pdf", f"inhalt-{i}") for i in range(n)]
    await nightly_detection(env)
    await env.work_all()
    ids = [(await env.reg.find_by_hash(sha(f"inhalt-{i}")))["id"] for i in range(n)]
    return f, paths, ids


async def test_consistent_inventory(env):  # AK-32
    await nas_sources(env, 5)
    r = await reconcile(env)
    assert r["state"] == "complete" and r["kind"] == "on_demand" and not r["guard_triggered"]
    assert all(v["gaps"] == 0 and v["repaired"] == 0 for v in r["summary"]["levels"].values()), r["summary"]
    assert await gaps(env, r["id"]) == []


async def test_level1_register_and_missing(env):  # AK-23, AK-24
    f, paths, ids = await nas_sources(env, 30)
    new = write(f"{f}/neu.pdf", "neu")
    os.remove(paths[0])
    r = await reconcile(env)
    lv1 = r["summary"]["levels"]["1"]
    assert (lv1["repaired"], lv1["reported"]) == (1, 1), r["summary"]
    src = await env.reg.find_by_hash(sha("neu"))
    assert src and src["locations"][0]["path"] == new
    assert src["events"][0]["event"] == "reconcile_registered"  # AK-34
    gone = await env.reg.get_source(ids[0])
    assert gone["locations"][0]["present"] is True and not gone["deleted"]  # only reported
    g = {x["gap"]: x for x in await gaps(env, r["id"], 1)}
    assert g["file_missing"]["action"] == "reported" and g["file_unregistered"]["action"] == "repaired"


async def test_level2_and_events(env):  # AK-26, AK-28, AK-34
    _, _, ids = await nas_sources(env, 80)
    a, b = ids[0], ids[1]
    pa = env.repo / (await env.reg.get_source(a))["path"]
    pa.unlink()
    await env.execute("UPDATE alice.sources SET deleted = TRUE, deleted_at = NOW() WHERE id = $1", b)
    r = await reconcile(env)
    assert r["summary"]["levels"]["2"]["repaired"] == 2, r["summary"]
    assert r["summary"]["levels"]["4"]["repaired"] == 1  # the deleted one's document row
    assert pa.exists()
    src_b = await env.reg.get_source(b)
    assert src_b["path"].startswith("deleted/")
    assert {e["event"] for e in (await env.reg.get_source(a))["events"]} >= {"reconcile_restored"}
    assert "reconcile_moved" in {e["event"] for e in src_b["events"]}


async def test_level2_orphan_reported(env):  # AK-27
    _, _, ids = await nas_sources(env, 2)
    text = (env.repo / (await env.reg.get_source(ids[0]))["path"]).read_text()
    stray = env.repo / "documents" / "stray.md"
    stray.write_text(text.replace(ids[0], "zzzzzzzzzzzz"))
    r = await reconcile(env)
    g = await gaps(env, r["id"], 2)
    assert [(x["gap"], x["action"]) for x in g] == [("markdown_orphan", "reported")]
    assert stray.read_text() == text.replace(ids[0], "zzzzzzzzzzzz")


async def test_level3_pending_too_long(env):  # AK-29, EC-6
    _, _, ids = await nas_sources(env, 3)
    a, b = ids[0], ids[1]
    p = await env.rebuilds.start("classify", "document", "admin")
    env.settings.stage_limit = 1000
    await env.rebuilds.tick()  # all three released: pending in the active run
    await env.execute("UPDATE alice.rebuild_items SET released_at = NULL, finished_at = NULL WHERE source_id = $1", a)
    await env.execute("DELETE FROM alice.rebuild_items WHERE source_id = $1", a)  # a: not part of the run
    await env.execute("ALTER TABLE alice.source_stages DISABLE TRIGGER trg_source_stages_updated_at")
    try:
        await env.execute("UPDATE alice.source_stages SET state = 'pending', rebuild_run = NULL, "
                          "updated_at = NOW() - interval '25 hours' WHERE source_id = ANY($1::text[]) "
                          "AND stage = 'classify'", [a, b])
    finally:
        await env.execute("ALTER TABLE alice.source_stages ENABLE TRIGGER trg_source_stages_updated_at")
    r = await reconcile(env)
    g = await gaps(env, r["id"], 3)
    assert [(x["source_id"], x["action"]) for x in g] == [(a, "reported")]
    assert "classify" in g[0]["detail"]
    assert p["id"]


async def test_level4(env):  # AK-30, AK-31
    _, _, ids = await nas_sources(env, 100)
    a, b = ids[0], ids[1]
    await env.execute("DELETE FROM alice.doc_documents WHERE id = $1", a)
    await env.execute("UPDATE alice.sources SET deleted = TRUE, deleted_at = NOW() WHERE id = $1", b)
    await env.execute("INSERT INTO alice.doc_bank_statements (document_id) VALUES ($1)", b)
    await env.execute("INSERT INTO alice.doc_bank_transactions (document_id, position, amount) VALUES ($1, 1, 1.5)", b)
    await env.execute("INSERT INTO alice.doc_documents (id, type, markdown_path) VALUES ('unknown00000', 'Document', 'x')")
    r = await reconcile(env)
    assert r["summary"]["levels"]["4"]["repaired"] == 3, r["summary"]
    assert (await env.stage(a, "database"))["state"] == "pending"
    assert await env.fetchval("SELECT count(*) FROM alice.doc_documents WHERE id = ANY($1::text[])",
                              [b, "unknown00000"]) == 0
    assert await env.fetchval("SELECT count(*) FROM alice.doc_bank_transactions WHERE document_id = $1", b) == 0
    ev = {e["event"] for e in (await env.reg.get_source(a))["events"]}
    assert "reconcile_db_retry" in ev
    assert "reconcile_db_removed" in {e["event"] for e in (await env.reg.get_source(b))["events"]}


async def test_mass_repair_guard(env):  # AK-33
    _, _, ids = await nas_sources(env, 100)
    paths = []
    for sid in ids[:6]:
        p = env.repo / (await env.reg.get_source(sid))["path"]
        p.unlink()
        paths.append(p)
    r = await reconcile(env)
    assert r["guard_triggered"] is True and r["state"] == "complete"
    lv2 = r["summary"]["levels"]["2"]
    assert (lv2["gaps"], lv2["repaired"], lv2["reported"]) == (6, 0, 6)
    assert not any(p.exists() for p in paths)
    assert any("Massenreparatur" in n for n in r["summary"]["notes"])


async def test_after_rebuild(env):  # AK-17
    await nas_sources(env, 2)
    p = await env.rebuilds.start("database", "document", "admin")
    await env.drive(p["id"])
    await env.reconciler.tick()
    await env.reconciler.task
    out = (await env.reconciler.list_results(10, 0))["items"]
    assert out[0]["kind"] == "after_rebuild" and out[0]["rebuild_run_id"] == p["id"]
    assert (await env.rebuilds.progress(p["id"]))["reconcile_id"] == out[0]["id"]
    await env.reconciler.tick()  # not twice
    assert (await env.reconciler.list_results(10, 0))["total"] == 1


async def test_waits_for_nightly_run(env, monkeypatch):  # AK-35
    import app.reconcile as rc

    monkeypatch.setattr(rc, "LEASE_WAIT_SECONDS", 0.05)
    await nas_sources(env, 1)
    env.det.running = "night"  # nightly run of the detection active
    rid = await env.reconciler.start("nightly")
    await asyncio.sleep(0.3)
    assert not env.reconciler.task.done()
    env.det.running = None
    await env.reconciler.task
    r = await env.reconciler.get_result(rid)
    assert r["state"] == "complete" and r["summary"]["hash_cycle"]["done"] == 1


async def test_nightly_rolling_hash(env):  # AK-36
    env.settings.hash_cycle_days = 3
    f = await folder(env)
    for i in range(9):
        write(f"{f}/{i}.pdf", f"inhalt-{i:02d}" * 5)
    await nightly_detection(env)
    await env.work_all()
    percents = []
    for _ in range(3):
        r = await reconcile(env, "nightly")
        percents.append(r["summary"]["hash_cycle"]["percent"])
    assert percents[-1] == 100.0 and percents[0] < 100.0
    assert await env.fetchval("SELECT count(*) FROM alice.detect_files WHERE rehashed_at IS NULL") == 0


async def test_rehash_changed_content(env):  # AK-25 via full re-hash on demand (AK-38)
    f = await folder(env)
    p = write(f"{f}/a.pdf", "AAAA", mtime=1_700_000_000)
    for i in range(30):
        write(f"{f}/x{i}.pdf", f"x{i}")
    await nightly_detection(env)
    await env.work_all()
    sid = (await env.reg.find_by_hash(sha("AAAA")))["id"]
    write(p, "BBBB", mtime=1_700_000_000)
    r = await reconcile(env, mode="full_rehash")
    assert r["kind"] == "on_demand" and r["mode"] == "full_rehash"
    assert r["summary"]["levels"]["1"]["repaired"] == 1, r["summary"]
    src = await env.reg.get_source(sid)
    assert src["hash"] == sha("BBBB") and src["stages"]["extract"]["state"] == "pending"
    assert "reconcile_hash_changed" in {e["event"] for e in src["events"]}


async def test_on_demand_and_second_rejected(env):  # AK-38, EC-12
    await nas_sources(env, 1)
    rid = await env.reconciler.start("on_demand")
    with pytest.raises(Busy409):
        await env.reconciler.start("on_demand")
    await env.reconciler.task
    assert (await env.reconciler.get_result(rid))["kind"] == "on_demand"


async def test_results_kept_and_logged(env, caplog):  # AK-39
    caplog.set_level(logging.INFO, logger="alice-etl-rebuild.reconcile")
    env.settings.retention_days = 30
    now = datetime.now(timezone.utc)
    for days in (31, 29, 15, 1):
        await env.execute("INSERT INTO alice.reconcile_results (kind, state, started_at, finished_at, summary) "
                          "VALUES ('nightly', 'complete', $1, $1, '{\"levels\": {}}')", now - timedelta(days=days))
    await nas_sources(env, 1)
    r = await reconcile(env)
    out = (await env.reconciler.list_results(100, 0))["items"]
    ages = sorted(round((now - datetime.fromisoformat(i["started_at"])).total_seconds() / 86400) for i in out)
    assert ages == [0, 1, 15, 29]
    for i in out:
        assert i["kind"] and i["state"] and "levels" in i["summary"] and "duration_seconds" in i
    assert f"Reconciliation {r['id']}" in caplog.text


async def test_register_unavailable_aborts(env, monkeypatch):  # AK-41
    _, _, ids = await nas_sources(env, 40)
    (env.repo / (await env.reg.get_source(ids[0]))["path"]).unlink()

    async def down(*a, **kw):
        raise Unavailable("Register nicht erreichbar: ConnectError")

    monkeypatch.setattr(env.registry, "repo_check", down)
    r = await reconcile(env)
    assert r["state"] == "incomplete" and "Register" in r["reason"]
    assert all(v["repaired"] == 0 for v in r["summary"]["levels"].values())
    assert not (env.repo / (await env.reg.get_source(ids[0]))["path"]).exists()


async def test_skipped_folder_named(env):  # AK-42
    f, paths, _ = await nas_sources(env, 2)
    for p in paths:
        os.remove(p)  # folder empty although files are known: share not mounted
    r = await reconcile(env)
    assert r["summary"]["levels"]["1"]["gaps"] == 0
    assert [s["folder"] for s in r["summary"]["skipped_folders"]] == [f]
    assert [g["gap"] for g in await gaps(env, r["id"], 1)] == ["folder_skipped"]


async def test_unreadable_on_rehash(env, monkeypatch):  # AK-43
    f, paths, ids = await nas_sources(env, 1)
    real = env.det.__class__  # noqa: F841
    import detection_app.reconcile as drc

    orig = drc.fsscan.sha256_file

    def denied(path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(drc.fsscan, "sha256_file", denied)
    r = await reconcile(env, mode="full_rehash")
    g = await gaps(env, r["id"], 1)
    assert [(x["gap"], x["action"]) for x in g] == [("file_unreadable", "reported")]
    assert (await env.reg.get_source(ids[0]))["hash"] == sha("inhalt-0")
    monkeypatch.setattr(drc.fsscan, "sha256_file", orig)
    r = await reconcile(env, "nightly")
    assert r["summary"]["hash_cycle"]["done"] == 1


async def test_detection_unreachable(env, monkeypatch):
    await nas_sources(env, 1)

    async def down(*a, **kw):
        raise Unavailable("Datei-Erkennung nicht erreichbar: ConnectError")

    monkeypatch.setattr(env.detection, "lease", down)
    r = await reconcile(env)
    assert r["state"] == "incomplete" and "Ebene 1" in r["reason"]
    assert r["summary"]["levels"]["2"]["gaps"] == 0  # the other levels still ran


async def test_nightly_schedule(env):
    env.settings.nightly_time = "03:00"
    env.settings.catchup_hours = 6
    slot = env.reconciler.nightly_slot(datetime(2026, 11, 24, 4, 0, tzinfo=timezone.utc))
    assert slot.astimezone(env.settings.tz).hour == 3
    late = datetime.now(timezone.utc)
    due = await env.reconciler.nightly_due(late)
    assert due == (late - env.reconciler.nightly_slot(late) <= timedelta(hours=6))
