"""PROJ-116 changes to the register: deleted/ folder, no work for deleted sources,
hand deletion below deleted/, reactivation, detect done on registration, in-place change."""
from datetime import datetime, timezone

from app import markdown as md

from .conftest import git
from .test_registry import claim_one, log, read_fm, register, stages

PATH = "/nas/scanner/scan_0042.pdf"


async def delete_source(reg, sid, path=PATH):
    r = await reg.remove_location(sid, {"path": path})
    assert r["deleted"]
    return await reg.get_source(sid)


async def test_deleted_markdown_moves_to_deleted_dir(reg, repo_dir):  # AK-11
    sid = (await register(reg))["id"]
    regular = (await reg.get_source(sid))["path"]
    src = await delete_source(reg, sid)
    assert src["path"] == f"deleted/{regular}"
    assert not (repo_dir / regular).exists() and (repo_dir / src["path"]).exists()
    fm, _ = read_fm(repo_dir, src["path"])
    assert fm["deleted"] and datetime.fromisoformat(fm["deleted"]) == src["deleted_at"]
    assert fm["locations"] == []
    follow = git(repo_dir, "log", "--follow", "--format=%s", "--", src["path"]).strip().splitlines()
    assert len(follow) == 2 and follow[-1].startswith("detect:")
    assert git(repo_dir, "status", "--porcelain").strip() == ""


async def test_deleted_source_not_claimed(reg):  # AK-12
    keep = (await register(reg, h="sha256:" + "k" * 16, path="/nas/keep.pdf"))["id"]
    sid = (await register(reg))["id"]
    await delete_source(reg, sid)
    assert (await stages(reg, sid))["extract"]["state"] == "pending"  # open stages stay as they are
    items = (await reg.claim("extract", 100))["items"]
    assert [i["source_id"] for i in items] == [keep]


async def test_deleted_source_not_claimed_without_redis(make_registry):  # AK-12 (register path)
    reg = await make_registry(redis=None)
    sid = (await register(reg))["id"]
    await delete_source(reg, sid)
    assert (await reg.claim("extract", 100))["items"] == []


async def test_reactivation_moves_back(reg, repo_dir):  # AK-13
    sid = (await register(reg))["id"]
    token = await claim_one(reg, "extract", sid)
    await reg.complete(sid, "extract", token)
    regular = (await reg.get_source(sid))["path"]
    text = (repo_dir / regular).read_text().replace("title: scan_0042.pdf", "title: Meine Rechnung")
    (repo_dir / regular).write_text(text)
    await reg.scan()  # hand correction → title in manual, file renamed
    regular = (await reg.get_source(sid))["path"]
    await delete_source(reg, sid)
    r = await register(reg, path="/nas/family/rechnung.pdf")
    assert r["id"] == sid and not r["created"] and r["reactivated"]
    src = await reg.get_source(sid)
    assert not src["deleted"] and src["deleted_at"] is None and src["path"] == regular
    fm, _ = read_fm(repo_dir, regular)
    assert "deleted" not in fm and fm["title"] == "Meine Rechnung" and fm["manual"] == ["title"]
    assert fm["locations"] == [{"path": "/nas/family/rechnung.pdf"}]
    st = await stages(reg, sid)
    assert st["extract"]["state"] == "done" and st["database"]["state"] == "pending"
    assert not (repo_dir / "deleted").exists() or not list((repo_dir / "deleted").rglob("*.md"))
    assert len(git(repo_dir, "log", "--follow", "--format=%s", "--", regular).strip().splitlines()) >= 4


async def test_hand_delete_in_deleted_dir_accepted(reg, repo_dir):  # AK-14
    sid = (await register(reg))["id"]
    src = await delete_source(reg, sid)
    (repo_dir / src["path"]).unlink()
    r = await reg.scan()
    assert r["removed"] == 1 and r["restored"] == 0
    assert not (repo_dir / src["path"]).exists()
    assert log(repo_dir, src["path"])[0] == f"Alice Hand-Korrektur|manual: remove {sid} scan_0042.pdf"
    after = await reg.get_source(sid)
    assert after["deleted"] and not any(e["level"] == "error" for e in after["events"])
    r = await reg.scan()  # nothing left to do, still no restore
    assert r["removed"] == 0 and r["restored"] == 0 and not (repo_dir / src["path"]).exists()


async def test_reappearing_after_hand_delete_restores_last_state(reg, repo_dir):  # AK-15
    sid = (await register(reg))["id"]
    await reg.write_document(sid, stage="extract", fields={"summary": "Text"}, content="Extrahierter Text")
    regular = (await reg.get_source(sid))["path"]
    src = await delete_source(reg, sid)
    (repo_dir / src["path"]).unlink()
    await reg.scan()
    r = await register(reg, path="/nas/back.pdf")
    assert r["reactivated"]
    after = await reg.get_source(sid)
    assert after["path"] == regular and not after["deleted"]
    fm, content = read_fm(repo_dir, regular)
    assert fm["summary"] == "Text" and "Extrahierter Text" in content and "deleted" not in fm
    assert fm["locations"] == [{"path": "/nas/back.pdf"}]


async def test_reappearing_without_history_recreates(reg, repo_dir, pool):  # AK-15 (not possible from git)
    sid = (await register(reg))["id"]
    token = await claim_one(reg, "extract", sid)
    await reg.complete(sid, "extract", token)
    src = await delete_source(reg, sid)
    (repo_dir / src["path"]).unlink()
    await reg.scan()
    async with pool.acquire() as con:  # simulate a blob that is no longer in git
        await con.execute("UPDATE alice.sources SET blob = $2 WHERE id = $1", sid, "0" * 40)
    await register(reg, path="/nas/back.pdf")
    after = await reg.get_source(sid)
    fm, content = read_fm(repo_dir, after["path"])
    assert not md.is_deleted_path(after["path"]) and fm["title"] == "scan_0042.pdf" and "back.pdf" in content
    assert after["stages"]["extract"]["state"] == "pending"


async def test_hand_edit_in_deleted_dir_taken_over_before_moving_back(reg, repo_dir):  # EC-10
    sid = (await register(reg))["id"]
    src = await delete_source(reg, sid)
    p = repo_dir / src["path"]
    p.write_text(p.read_text().replace("type: null", "type: Invoice"))
    await register(reg, path="/nas/back.pdf")
    after = await reg.get_source(sid)
    fm, _ = read_fm(repo_dir, after["path"])
    assert fm["type"] == "Invoice" and "type" in fm["manual"] and not md.is_deleted_path(after["path"])


async def test_old_deleted_sources_are_moved_by_scan(reg, repo_dir, pool):
    """Sources deleted before PROJ-116 still have their markdown outside deleted/."""
    sid = (await register(reg))["id"]
    async with pool.acquire() as con:
        await con.execute("UPDATE alice.source_locations SET present = FALSE WHERE source_id = $1", sid)
        await con.execute("UPDATE alice.sources SET deleted = TRUE, deleted_at = NOW() WHERE id = $1", sid)
    r = await reg.scan()
    assert r["moved"] == 1
    path = (await reg.get_source(sid))["path"]
    assert md.is_deleted_path(path) and read_fm(repo_dir, path)[0]["deleted"]


async def test_register_complete_marks_detect_done(reg):
    r = await reg.register(kind="document", hash="sha256:" + "d" * 16, title="a.pdf", location={"path": "/nas/a.pdf"},
                           complete=True)
    st = await stages(reg, r["id"])
    assert st["detect"]["state"] == "done" and st["extract"]["state"] == "pending"
    items = (await reg.claim("detect", 10))["items"]
    assert r["id"] not in [i["source_id"] for i in items]


async def test_update_original_resets_stages_after_detect(reg, repo_dir):  # AK-16
    sid = (await reg.register(kind="document", hash="sha256:" + "e" * 16, title="a.pdf",
                              location={"path": "/nas/a.pdf"}, complete=True))["id"]
    for stage in ("extract", "classify", "thumbnail"):
        await reg.complete(sid, stage, await claim_one(reg, stage, sid))
    p = repo_dir / (await reg.get_source(sid))["path"]
    p.write_text(p.read_text().replace("title: a.pdf", "title: Handtitel"))
    await reg.scan()
    r = await reg.update_original(sid, hash="sha256:" + "f" * 16, size=5,
                                  modified=datetime(2026, 11, 22, tzinfo=timezone.utc))
    assert {"extract", "classify", "thumbnail"} <= set(r["reset"])
    st = await stages(reg, sid)
    assert st["detect"]["state"] == "done"
    assert all(st[s]["state"] == "pending" for s in ("extract", "classify", "database", "rag", "wiki", "thumbnail"))
    src = await reg.get_source(sid)
    fm, _ = read_fm(repo_dir, src["path"])
    assert src["id"] == sid and fm["hash"] == "sha256:" + "f" * 16 and fm["size"] == 5 and fm["title"] == "Handtitel"
