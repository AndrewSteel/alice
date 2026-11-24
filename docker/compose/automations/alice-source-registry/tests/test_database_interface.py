"""Interface extensions for the database stage (PROJ-119): register fields `locations`/`deleted` as
reset triggers for stages naming them, claim with deleted sources (`include_deleted`)."""
from .test_registry import _done, register, stages

PATH = "/nas/scanner/scan_0042.pdf"


async def _classified(reg, sid):
    await _done(reg, sid, "extract", "classify")


async def _claim_db(reg):
    return (await reg.claim("database", 100, ["document"], ["classify"], True))["items"]


async def test_deletion_and_return_reset_database_only(reg):
    sid = (await register(reg))["id"]
    await _classified(reg, sid)
    await _done(reg, sid, "database", "rag")
    await reg.remove_location(sid, {"path": PATH})
    st = await stages(reg, sid)
    assert st["database"]["state"] == "pending" and st["rag"]["state"] == "done"
    items = await _claim_db(reg)
    await reg.complete(sid, "database", items[0]["token"])
    await reg.add_location(sid, {"path": PATH})
    assert (await stages(reg, sid))["database"]["state"] == "pending"


async def test_claim_include_deleted(reg):
    live = (await register(reg, h="sha256:" + "l" * 16, path="/nas/live.pdf"))["id"]
    gone = (await register(reg))["id"]  # classify still pending
    unready = (await register(reg, h="sha256:" + "u" * 16, path="/nas/unready.pdf"))["id"]
    await _classified(reg, live)
    await reg.remove_location(gone, {"path": PATH})
    # without the option: deleted sources are not handed out (PROJ-116)
    plain = (await reg.claim("database", 100, ["document"], ["classify"]))["items"]
    assert [i["source_id"] for i in plain] == [live]
    await reg.release(live, "database", plain[0]["token"])
    items = {i["source_id"]: i for i in await _claim_db(reg)}
    assert set(items) == {live, gone}  # deleted one regardless of `requires`, unready one not
    assert items[gone]["deleted"] is True and items[live]["deleted"] is False
    assert unready not in items


async def test_locked_source_deleted_and_back(reg, repo_dir):
    sid = (await register(reg))["id"]
    await _classified(reg, sid)
    await _done(reg, sid, "database")
    path = repo_dir / (await reg.get_source(sid))["path"]
    path.write_text(path.read_text().replace("kind: document", "kind: [broken"))
    await reg.scan()
    assert (await reg.get_source(sid))["repo_error"]
    await reg.remove_location(sid, {"path": PATH})
    assert (await stages(reg, sid))["database"]["state"] == "pending"
    items = await _claim_db(reg)  # locked, but deleted: handed out (markdown is not read)
    assert [i["source_id"] for i in items] == [sid]
    await reg.complete(sid, "database", items[0]["token"])
    await reg.add_location(sid, {"path": PATH})
    assert (await stages(reg, sid))["database"]["state"] == "pending"
    assert await _claim_db(reg) == []  # back and locked: not handed out until repaired
