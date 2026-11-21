"""Integration tests: register + repo with a throwaway PostgreSQL and a temporary git repo."""
import asyncio
import os
import shutil
from datetime import datetime, timezone

import pytest
import yaml

from app import markdown as md
from app.gitrepo import RepoUnavailable
from app.service import Conflict, Locked

from .conftest import git

NOV = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)


async def register(reg, h="sha256:" + "a" * 16, title="scan_0042.pdf", path="/nas/scanner/scan_0042.pdf",
                   kind="document", **kw):
    return await reg.register(kind=kind, hash=h, title=title, location={"path": path}, size=1234,
                              modified=NOV, captured=kw.pop("captured", NOV), **kw)


def read_fm(repo_dir, rel):
    return md.parse((repo_dir / rel).read_text())


def log(repo_dir, *paths, fmt="%an|%s"):
    return git(repo_dir, "log", f"--format={fmt}", "--", *paths).strip().splitlines()


async def stages(reg, sid):
    return (await reg.get_source(sid))["stages"]


async def claim_one(reg, stage, sid):
    items = (await reg.claim(stage, 100))["items"]
    for other in items:  # give back what this test did not ask for
        if other["source_id"] != sid:
            await reg.release(other["source_id"], stage, other["token"])
    item = next(i for i in items if i["source_id"] == sid)
    return item["token"]


# ---------------------------------------------------------------- repo + markdown
async def test_startup_initializes_repo(reg, repo_dir):  # AK-1
    assert reg.available
    assert (repo_dir / ".git").is_dir() and (repo_dir / "README.md").exists()


async def test_foreign_folder_aborts_start(make_registry, repo_dir):  # AK-3
    from app.gitrepo import RepoForeign

    (repo_dir / "foo.txt").write_text("x")
    with pytest.raises(RepoForeign):
        await make_registry()
    assert os.listdir(repo_dir) == ["foo.txt"]


async def test_register_writes_markdown(reg, repo_dir):  # AK-4, AK-7, AK-9, AK-11
    r = await register(reg)
    sid = r["id"]
    assert r["created"] and len(sid) == 12
    assert r["path"] == f"documents/2026/11/{sid}-scan-0042-pdf.md"
    fm, content = read_fm(repo_dir, r["path"])
    md.validate(fm, source_id=sid, kind="document")
    assert fm["title"] == "scan_0042.pdf"
    assert fm["locations"] == [{"path": "/nas/scanner/scan_0042.pdf"}]
    assert fm["hash"] == "sha256:" + "a" * 16 and fm["size"] == 1234
    assert fm["parents"] == [] and fm["manual"] == [] and fm["language"] is None and fm["type"] is None
    assert "# scan_0042.pdf" in (repo_dir / r["path"]).read_text()
    assert "scan_0042.pdf" in content  # link to the original
    assert not {"state", "attempts", "last_error", "next_retry_at"} & set(fm)
    assert log(repo_dir, r["path"]) == [f"Alice ETL|detect: {sid} scan_0042.pdf"]
    src = await reg.get_source(sid)
    assert src["kind"] == "document" and len(src["locations"]) == 1
    assert {s: v["state"] for s, v in src["stages"].items()} == {s: "pending" for s in
                                                                 ("detect", "extract", "classify", "database",
                                                                  "rag", "wiki", "thumbnail")}
    assert git(repo_dir, "status", "--porcelain") == ""


async def test_title_change_renames_file(reg, repo_dir):  # AK-5, AK-7
    sid = (await register(reg))["id"]
    old = (await reg.get_source(sid))["path"]
    r = await reg.write_document(sid, stage="classify", fields={"title": "Stromrechnung Stadtwerke Okt 2026",
                                                                 "type": "Invoice"})
    assert r["path"] == f"documents/2026/11/{sid}-stromrechnung-stadtwerke-okt-2026.md"
    assert not (repo_dir / old).exists()
    fm, _ = read_fm(repo_dir, r["path"])
    assert fm["title"] == "Stromrechnung Stadtwerke Okt 2026" and fm["type"] == "Invoice"
    follow = git(repo_dir, "log", "--follow", "--format=%s", "--", r["path"]).strip().splitlines()
    assert follow == [f"classify: {sid} Stromrechnung Stadtwerke Okt 2026", f"detect: {sid} scan_0042.pdf"]
    last = git(repo_dir, "show", "--stat", "--format=%an", "HEAD")
    assert last.startswith("Alice ETL")
    assert (await reg.read_document(sid))["frontmatter"]["title"] == "Stromrechnung Stadtwerke Okt 2026"


async def test_location_change_only_touches_locations(reg, repo_dir):  # AK-6
    sid = (await register(reg))["id"]
    path = (await reg.get_source(sid))["path"]
    before, content_before = read_fm(repo_dir, path)
    await reg.add_location(sid, {"path": "/nas/family/moved.pdf"})
    await reg.remove_location(sid, {"path": "/nas/scanner/scan_0042.pdf"})
    assert (await reg.get_source(sid))["path"] == path
    after, content_after = read_fm(repo_dir, path)
    assert after["locations"] == [{"path": "/nas/family/moved.pdf"}]
    assert {k: v for k, v in before.items() if k != "locations"} == {k: v for k, v in after.items()
                                                                      if k != "locations"}
    assert content_after == content_before
    assert all(s["state"] == "pending" for s in (await stages(reg, sid)).values())
    assert len(log(repo_dir, path)) == 3


async def test_batch_commits_max_500(make_registry, repo_dir):  # AK-8
    reg = await make_registry()
    ids = []
    for i in range(1200):
        r = await register(reg, h=f"sha256:{i:016d}", title=f"f{i}.pdf", path=f"/nas/f{i}.pdf",
                           stage="extract", batch=True)
        ids.append(r["id"])
    await reg.flush_due(force=True)
    subjects = log(repo_dir, "documents", fmt="%s")[:-1]  # last one: init
    assert subjects == ["rebuild: extract 200 sources", "rebuild: extract 500 sources", "rebuild: extract 500 sources"]
    counts = [len([x for x in git(repo_dir, "show", "--name-only", "--format=", f"HEAD~{n}").splitlines() if x])
              for n in range(3)]
    assert sorted(counts) == [200, 500, 500]
    assert git(repo_dir, "status", "--porcelain") == ""


async def test_batch_closes_after_time_limit(make_registry, repo_dir):  # AK-8
    reg = await make_registry(batch_max_seconds=1)
    await register(reg, stage="extract", batch=True)
    assert await reg.flush_due() == 0
    await asyncio.sleep(1.1)
    assert await reg.flush_due() == 1
    assert log(repo_dir, "documents", fmt="%s")[0] == "rebuild: extract 1 sources"


@pytest.mark.parametrize("kind,folder", [("audio", "audio"), ("video", "video")])
async def test_audio_video_skipped(reg, repo_dir, kind, folder):  # AK-10
    r = await register(reg, kind=kind, title="aufnahme.mp3")
    assert r["path"].startswith(f"{folder}/2026/11/")
    fm, content = read_fm(repo_dir, r["path"])
    assert fm["kind"] == kind and "/nas/scanner/scan_0042.pdf" in content
    st = await stages(reg, r["id"])
    assert st.pop("detect")["state"] == "pending"
    assert {v["state"] for v in st.values()} == {"skipped"}


# ---------------------------------------------------------------- register + locations
async def test_same_hash_second_location(reg, repo_dir):  # AK-12
    sid = (await register(reg))["id"]
    tok = await claim_one(reg, "extract", sid)
    await reg.complete(sid, "extract", tok)
    r = await register(reg, path="/nas/family/kopie.pdf")
    assert r["id"] == sid and not r["created"]
    assert len(list((repo_dir / "documents/2026/11").glob("*.md"))) == 1
    src = await reg.get_source(sid)
    assert [l["path"] for l in src["locations"]] == ["/nas/scanner/scan_0042.pdf", "/nas/family/kopie.pdf"]
    assert src["stages"]["extract"]["state"] == "done"
    fm, _ = read_fm(repo_dir, src["path"])
    assert len(fm["locations"]) == 2


async def test_attachment_parents(reg, repo_dir):  # AK-13
    file_id = (await register(reg))["id"]
    mail = await reg.register(kind="email", hash="sha256:" + "m" * 16, title="Ihre Rechnung",
                              location={"mailbox": "inbox", "message_id": "<1@example.invalid>"}, captured=NOV)
    r = await reg.register(kind="document", hash="sha256:" + "a" * 16, title="rechnung.pdf",
                           location={"mailbox": "inbox", "message_id": "<1@example.invalid>"},
                           parents=[mail["id"]])
    assert r["id"] == file_id and not r["created"]
    src = await reg.get_source(file_id)
    assert src["parents"] == [mail["id"]]
    assert (await reg.get_source(mail["id"]))["children"] == [file_id]
    fm, _ = read_fm(repo_dir, src["path"])
    assert fm["parents"] == [mail["id"]]
    assert {"mailbox": "inbox", "message_id": "<1@example.invalid>"} in fm["locations"]


async def test_deleted_only_without_locations(reg):  # AK-14
    sid = (await register(reg))["id"]
    await reg.add_location(sid, {"path": "/nas/b.pdf"})
    r = await reg.remove_location(sid, {"path": "/nas/scanner/scan_0042.pdf"})
    assert not r["deleted"] and not (await reg.get_source(sid))["deleted"]
    r = await reg.remove_location(sid, {"path": "/nas/b.pdf"})
    src = await reg.get_source(sid)
    assert r["deleted"] and src["deleted"] and src["deleted_at"]
    assert len(src["locations"]) == 2 and not any(l["present"] for l in src["locations"])


async def test_update_original_hash(reg, repo_dir):  # EC-8
    sid = (await register(reg))["id"]
    await reg.update_original(sid, hash="sha256:" + "b" * 16, size=99, modified=NOV)
    fm, _ = read_fm(repo_dir, (await reg.get_source(sid))["path"])
    assert fm["hash"] == "sha256:" + "b" * 16 and fm["size"] == 99
    other = (await register(reg, h="sha256:" + "c" * 16, path="/nas/c.pdf"))["id"]
    with pytest.raises(Conflict):
        await reg.update_original(other, hash="sha256:" + "b" * 16, size=1, modified=None)


# ---------------------------------------------------------------- stages
async def test_exclusive_claim(reg):  # AK-15
    sid = (await register(reg))["id"]
    a, b = await asyncio.gather(reg.claim("extract", 10), reg.claim("extract", 10))
    winners = [i for i in a["items"] + b["items"] if i["source_id"] == sid]
    assert len(winners) == 1
    assert (await stages(reg, sid))["extract"]["state"] == "running"


async def test_exclusive_claim_without_redis(make_registry):  # AK-15 (register path)
    reg = await make_registry(redis=None)
    sid = (await register(reg))["id"]
    results = await asyncio.gather(*(reg.claim("extract", 10) for _ in range(5)))
    assert sum(1 for r in results for i in r["items"] if i["source_id"] == sid) == 1


async def test_fail_backoff_and_permanent(reg, pool):  # AK-16, AK-17, AK-18
    sid = (await register(reg))["id"]
    expected = [60, 300, 1800, 7200]
    for n in range(1, 6):
        if n > 1:  # make the retry due
            async with pool.acquire() as con:
                await con.execute("UPDATE alice.source_stages SET next_retry_at = NOW() - interval '1 s' "
                                  "WHERE source_id = $1 AND stage = 'extract'", sid)
        tok = await claim_one(reg, "extract", sid)
        row = await reg.fail(sid, "extract", tok, f"Fehler {n}")
        assert row["attempts"] == n and row["last_error"] == f"Fehler {n}"
        if n < 5:
            assert row["state"] == "failed"
            delta = (row["next_retry_at"] - row["last_attempt_at"]).total_seconds()
            assert abs(delta - expected[n - 1]) < 2
            # not due yet → not claimable
            assert not [i for i in (await reg.claim("extract", 10))["items"] if i["source_id"] == sid]
        else:
            assert row["state"] == "failed_permanent" and row["next_retry_at"] is None
            assert row["last_attempt_at"]
    assert not [i for i in (await reg.claim("extract", 10))["items"] if i["source_id"] == sid]
    row = await reg.retry(sid, "extract")
    assert row["state"] == "pending" and row["attempts"] == 0
    assert await claim_one(reg, "extract", sid)


async def test_complete_requires_token(reg):
    sid = (await register(reg))["id"]
    await claim_one(reg, "extract", sid)
    with pytest.raises(Conflict):
        await reg.complete(sid, "extract", "00000000-0000-0000-0000-000000000000")


async def test_stale_running_back_to_pending(make_registry, pool):  # AK-19
    reg = await make_registry(stale_running_seconds=60)
    sid = (await register(reg))["id"]
    await claim_one(reg, "extract", sid)
    async with pool.acquire() as con:
        await con.execute("UPDATE alice.source_stages SET started_at = NOW() - interval '2 min' "
                          "WHERE source_id = $1 AND stage = 'extract'", sid)
    assert await reg.reset_stale() == 1
    st = (await stages(reg, sid))["extract"]
    assert st["state"] == "pending" and st["attempts"] == 0


async def _done(reg, sid, *names):
    for name in names:
        await reg.complete(sid, name, await claim_one(reg, name, sid))


async def test_content_change_resets_dependents(reg):  # AK-20
    sid = (await register(reg))["id"]
    await _done(reg, sid, "extract", "database", "rag", "wiki")
    r = await reg.write_document(sid, stage="extract", content="Neuer Text", fields={"language": "de"})
    assert sorted(r["reset"]) == ["database", "rag", "wiki"]
    st = await stages(reg, sid)
    assert [st[s]["state"] for s in ("extract", "database", "rag", "wiki")] == ["done", "pending", "pending", "pending"]


async def test_location_change_does_not_reset(reg):
    sid = (await register(reg))["id"]
    await _done(reg, sid, "database")
    await reg.add_location(sid, {"path": "/nas/other.pdf"})
    assert (await stages(reg, sid))["database"]["state"] == "done"


async def test_new_stage_for_existing_sources(reg):  # AK-21
    doc = (await register(reg))["id"]
    aud = (await register(reg, h="sha256:" + "v" * 16, kind="audio", path="/nas/a.mp3"))["id"]
    r = await reg.add_stage(name="ocr_check", position=25, skip_kinds=["audio", "video"],
                            resets_on_content_change=False)
    assert r["sources"] == 2
    assert (await stages(reg, doc))["ocr_check"]["state"] == "pending"
    assert (await stages(reg, aud))["ocr_check"]["state"] == "skipped"
    assert await claim_one(reg, "ocr_check", doc)


async def test_queue_rebuilt_after_redis_flush(reg, fake_redis, pool):  # AK-22
    a = (await register(reg))["id"]
    b = (await register(reg, h="sha256:" + "b" * 16, path="/nas/b.pdf"))["id"]
    tok = await claim_one(reg, "extract", b)
    await reg.fail(sid := b, "extract", tok, "x")
    async with pool.acquire() as con:
        await con.execute("UPDATE alice.source_stages SET next_retry_at = NOW() - interval '1 s' "
                          "WHERE source_id = $1 AND stage = 'extract'", sid)
    await fake_redis.flushall()
    assert not await reg.queue.is_ready()
    await reg.tick()  # monitor notices the missing marker and rebuilds
    assert await reg.queue.is_ready()
    assert set(await reg.queue.due("extract", 10)) == {a, b}
    got = {i["source_id"] for i in (await reg.claim("extract", 10))["items"]}
    assert got == {a, b}


async def test_queue_with_real_redis(make_registry):  # AK-22 against a real Redis
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL not set")
    import redis.asyncio as aioredis

    client = aioredis.from_url(url)
    await client.flushdb()
    reg = await make_registry(redis=client)
    await reg.resync_queue()
    sid = (await register(reg))["id"]
    await client.flushdb()
    await reg.tick()
    assert sid in await reg.queue.due("extract", 10)
    assert await claim_one(reg, "extract", sid)
    await client.flushdb()
    await client.aclose()


# ---------------------------------------------------------------- hand corrections
def edit(repo_dir, rel, fn):
    p = repo_dir / rel
    fm, content = md.parse(p.read_text())
    fm, content = fn(fm, content)
    p.write_text(md.render(fm, content))


async def test_uncommitted_hand_edit(reg, repo_dir):  # AK-23
    assert reg.s.scan_interval_seconds <= 300
    sid = (await register(reg))["id"]
    await _done(reg, sid, "database", "rag", "wiki")
    path = (await reg.get_source(sid))["path"]
    edit(repo_dir, path, lambda fm, c: ({**fm, "title": "Hand Titel"}, "Von Hand geschrieben\n"))
    res = await reg.scan()
    assert res["accepted"] == 1
    src = await reg.get_source(sid)
    assert src["path"].endswith(f"{sid}-hand-titel.md") and not (repo_dir / path).exists()
    fm, content = read_fm(repo_dir, src["path"])
    assert set(fm["manual"]) == {"title", "content"} and content == "Von Hand geschrieben\n"
    assert log(repo_dir, src["path"])[0] == f"Alice Hand-Korrektur|manual: {sid} Hand Titel"
    assert git(repo_dir, "status", "--porcelain") == ""
    assert [src["stages"][s]["state"] for s in ("database", "rag", "wiki")] == ["pending"] * 3
    assert (await reg.scan())["accepted"] == 0  # idempotent


async def test_human_commit_is_hand_correction(reg, repo_dir):  # AK-24
    sid = (await register(reg))["id"]
    await _done(reg, sid, "database")
    path = (await reg.get_source(sid))["path"]
    edit(repo_dir, path, lambda fm, c: ({**fm, "type": "Contract"}, c))
    git(repo_dir, "-c", "user.name=Mensch", "-c", "user.email=m@example.invalid", "commit", "-qam", "fix type")
    assert (await reg.scan())["accepted"] == 1
    fm, _ = read_fm(repo_dir, path)
    assert fm["manual"] == ["type"] and fm["type"] == "Contract"
    assert log(repo_dir, path, fmt="%an")[:2] == ["Alice Hand-Korrektur", "Mensch"]
    assert (await stages(reg, sid))["database"]["state"] == "pending"


async def test_manual_fields_protected(reg, repo_dir):  # AK-25, AK-26, EC-3
    sid = (await register(reg))["id"]
    path = (await reg.get_source(sid))["path"]
    edit(repo_dir, path, lambda fm, c: ({**fm, "title": "Hand Titel"}, c))
    await reg.scan()
    r = await reg.write_document(sid, stage="classify", fields={"title": "LLM Titel", "type": "Invoice"})
    fm, _ = read_fm(repo_dir, r["path"])
    assert fm["title"] == "Hand Titel" and fm["type"] == "Invoice"
    assert r["path"].endswith("-hand-titel.md")
    # human releases the field again (AK-26)
    edit(repo_dir, r["path"], lambda fm, c: ({**fm, "manual": []}, c))
    await reg.scan()
    fm, _ = read_fm(repo_dir, r["path"])
    assert fm["manual"] == []
    r = await reg.write_document(sid, stage="classify", fields={"title": "LLM Titel"})
    fm, _ = read_fm(repo_dir, r["path"])
    assert fm["title"] == "LLM Titel" and r["path"].endswith("-llm-titel.md")


async def test_manual_content_protected(reg, repo_dir):  # AK-25 (content)
    sid = (await register(reg))["id"]
    path = (await reg.get_source(sid))["path"]
    edit(repo_dir, path, lambda fm, c: (fm, "Hand Inhalt\n"))
    await reg.scan()
    await reg.write_document(sid, stage="extract", content="OCR Inhalt", fields={"language": "de"})
    fm, content = read_fm(repo_dir, path)
    assert content == "Hand Inhalt\n" and fm["language"] == "de"


async def test_write_commits_pending_hand_edit_first(reg, repo_dir):  # AK-27
    sid = (await register(reg))["id"]
    path = (await reg.get_source(sid))["path"]
    edit(repo_dir, path, lambda fm, c: ({**fm, "type": "Contract"}, c))
    r = await reg.write_document(sid, stage="extract", content="OCR", fields={"type": "Invoice", "language": "de"})
    fm, content = read_fm(repo_dir, r["path"])
    assert fm["type"] == "Contract" and fm["manual"] == ["type"] and content == "OCR\n" and fm["language"] == "de"
    assert log(repo_dir, path)[:2] == [f"Alice ETL|extract: {sid} scan_0042.pdf",
                                       f"Alice Hand-Korrektur|manual: {sid} scan_0042.pdf"]


@pytest.mark.parametrize("breaker,needle", [
    (lambda t: t.replace("title:", "title: [kaputt", 1), "YAML"),
    (lambda t: t.replace("hash:", "hush:", 1), "Pflichtfeld fehlt: hash"),
    (lambda t: t.replace("id: ", "id: x", 1), "'id'"),
])
async def test_invalid_hand_edit_locks_until_repaired(reg, repo_dir, breaker, needle):  # AK-28, AK-29
    sid = (await register(reg))["id"]
    await _done(reg, sid, "database")
    path = (await reg.get_source(sid))["path"]
    good = (repo_dir / path).read_text()
    broken = breaker(good)
    (repo_dir / path).write_text(broken)
    res = await reg.scan()
    assert res["locked"] == 1
    src = await reg.get_source(sid)
    assert needle in src["repo_error"]
    assert src["stages"]["database"]["state"] == "done"  # derived data stays
    assert (repo_dir / path).read_text() == broken  # not overwritten
    with pytest.raises(Locked):
        await reg.write_document(sid, stage="classify", fields={"type": "Invoice"})
    assert not [i for i in (await reg.claim("extract", 10))["items"] if i["source_id"] == sid]
    await reg.scan()
    assert (repo_dir / path).read_text() == broken
    # repaired with a real change
    fixed = good.replace("type: null", "type: Contract")
    (repo_dir / path).write_text(fixed)
    res = await reg.scan()
    assert res["accepted"] == 1
    src = await reg.get_source(sid)
    assert src["repo_error"] is None
    fm, _ = read_fm(repo_dir, src["path"])
    assert fm["type"] == "Contract" and "type" in fm["manual"]
    assert src["stages"]["database"]["state"] == "pending"
    await reg.write_document(sid, stage="classify", fields={"language": "de"})


async def test_invalid_then_reverted_unlocks(reg, repo_dir):  # AK-29 (revert to last state)
    sid = (await register(reg))["id"]
    path = (await reg.get_source(sid))["path"]
    good = (repo_dir / path).read_text()
    (repo_dir / path).write_text("kaputt")
    await reg.scan()
    assert (await reg.get_source(sid))["repo_error"]
    (repo_dir / path).write_text(good)
    await reg.scan()
    assert (await reg.get_source(sid))["repo_error"] is None


async def test_moved_file_is_put_back(reg, repo_dir):  # EC-4
    sid = (await register(reg))["id"]
    path = (await reg.get_source(sid))["path"]
    (repo_dir / "documents" / "anders.md").write_bytes((repo_dir / path).read_bytes())
    (repo_dir / path).unlink()
    await reg.scan()
    assert (repo_dir / path).exists() and not (repo_dir / "documents" / "anders.md").exists()
    fm, _ = read_fm(repo_dir, path)
    assert fm["manual"] == []
    assert git(repo_dir, "status", "--porcelain") == ""


async def test_deleted_file_restored(reg, repo_dir):  # EC-5
    sid = (await register(reg))["id"]
    path = (await reg.get_source(sid))["path"]
    content = (repo_dir / path).read_text()
    (repo_dir / path).unlink()
    assert (await reg.scan())["restored"] == 1
    assert (repo_dir / path).read_text() == content
    events = (await reg.get_source(sid))["events"]
    assert events[0]["event"] == "file_deleted" and events[0]["level"] == "error"


async def test_stray_markdown_left_alone(reg, repo_dir, caplog):  # EC-6
    await register(reg)
    stray = repo_dir / "documents" / "notiz.md"
    stray.write_text("# Notiz\n")
    await reg.scan()
    assert stray.read_text() == "# Notiz\n"
    assert "does not belong to a known source" in caplog.text


async def test_restart_commits_leftover_pipeline_files(make_registry, repo_dir):  # EC-7
    reg = await make_registry()
    sid = (await register(reg, batch=True, stage="extract"))["id"]
    path = (await reg.get_source(sid))["path"]
    assert path in git(repo_dir, "status", "--porcelain", "-uall")
    reg2 = await make_registry()  # crash: batch lost in memory
    res = await reg2.scan()
    assert res["recovered"] == 1 and res["accepted"] == 0
    assert log(repo_dir, path) == ["Alice ETL|rebuild: recover 1 sources"]
    assert (await reg2.get_source(sid))["stages"]["database"]["state"] == "pending"
    assert git(repo_dir, "status", "--porcelain") == ""


async def test_parallel_writes_serialized(reg, repo_dir):  # EC-9
    ids = [(await register(reg, h=f"sha256:{i:016d}", path=f"/nas/{i}.pdf"))["id"] for i in range(5)]
    await asyncio.gather(*(reg.write_document(sid, stage="extract", content=f"T{sid}") for sid in ids))
    for sid in ids:
        path = (await reg.get_source(sid))["path"]
        files = git(repo_dir, "show", "--name-only", "--format=", log(repo_dir, path, fmt="%H")[0]).split()
        assert files == [path]


async def test_old_schema_file_extended(reg, repo_dir):  # EC-10
    sid = (await register(reg))["id"]
    path = (await reg.get_source(sid))["path"]
    r = await reg.write_document(sid, stage="classify", fields={"vendor": "Stadtwerke"})
    fm, _ = read_fm(repo_dir, r["path"])
    assert fm["vendor"] == "Stadtwerke" and fm["schema"] == 1


# ---------------------------------------------------------------- NAS outage
async def test_repo_unavailable_pauses(reg, repo_dir, caplog):  # AK-30, AK-31
    sid = (await register(reg))["id"]
    path = (await reg.get_source(sid))["path"]
    away = repo_dir.parent / "away"
    repo_dir.rename(away)
    await reg.tick()
    assert not reg.available and "nicht erreichbar" in reg.unavailable_reason
    assert "processing paused" in caplog.text
    res = await reg.claim("extract", 10)
    assert res["paused"] and res["items"] == []
    with pytest.raises(RepoUnavailable):
        await reg.write_document(sid, stage="extract", content="x")
    st = (await stages(reg, sid))["extract"]
    assert st["state"] == "pending" and st["attempts"] == 0
    assert not repo_dir.exists()  # never re-created in an empty mount point
    # hand edit while the service could not see the folder
    edit(away, path, lambda fm, c: ({**fm, "type": "Contract"}, c))
    away.rename(repo_dir)
    await reg.tick()
    assert reg.available
    fm, _ = read_fm(repo_dir, path)
    assert fm["manual"] == ["type"]
    assert await claim_one(reg, "extract", sid)
