"""End-to-end: detection service + real register + temporary git repo + throwaway PostgreSQL."""
import hashlib
import logging
import os
import shutil

import pytest

from app import fsscan

from .conftest import git, run


def write(path, content: bytes | str = b"content", mtime=None):
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content.encode() if isinstance(content, str) else content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def sha(content: bytes | str) -> str:
    return "sha256:" + hashlib.sha256(content.encode() if isinstance(content, str) else content).hexdigest()


async def source(registry, content):
    return await registry.by_hash(sha(content))


def present(src):
    return sorted(loc["path"] for loc in src["locations"] if loc["present"])


async def settle(det, n=2):
    for _ in range(n):
        r = await run(det)
        assert r["state"] == "done", r


# ---------------------------------------------------------------- new files
async def test_new_file_registered_after_two_scans(det, registry, add_folder, nas, repo_dir):  # AK-1
    folder = await add_folder(nas / "share" / "scanner")
    await settle(det)
    p = write(f"{folder}/rechnung.pdf", "PDF-1")
    await run(det)
    assert await source(registry, "PDF-1") is None
    await run(det)
    src = await source(registry, "PDF-1")
    assert src["kind"] == "document" and src["hash"] == sha("PDF-1") and src["size"] == 5
    assert src["modified"] and present(src) == [p] and src["title"] == "rechnung.pdf"
    assert (repo_dir / src["path"]).exists()
    assert src["stages"]["detect"]["state"] == "done" and src["stages"]["extract"]["state"] == "pending"


async def test_growing_file_waits(det, registry, add_folder, nas):  # AK-2
    folder = await add_folder(nas / "share" / "in")
    p = write(f"{folder}/big.pdf", "part")
    await run(det)
    with open(p, "ab") as f:
        f.write(b"-more")
    await run(det)
    assert await source(registry, "part-more") is None
    await run(det)
    assert present(await source(registry, "part-more")) == [p]


async def test_copy_with_old_mtime_detected(det, registry, add_folder, nas):  # AK-3
    folder = await add_folder(nas / "share" / "docs")
    write(f"{folder}/sub/a.pdf", "A")
    await settle(det, 3)
    p = write(f"{folder}/sub/old.pdf", "OLD", mtime=946684800)  # year 2000
    await settle(det)
    assert present(await source(registry, "OLD")) == [p]


async def test_kinds_by_extension(det, registry, add_folder, nas):  # AK-5
    folder = await add_folder(nas / "share" / "mix")
    files = {"a.PDF": "document", "b.Docx": "document", "c.ods": "document", "d.JpG": "image", "e.heic": "image",
             "f.TIFF": "image", "g.Mp3": "audio", "h.flac": "audio", "i.MOV": "video", "j.webm": "video"}
    for name in files:
        write(f"{folder}/{name}", f"content-{name}")
    await settle(det)
    for name, kind in files.items():
        src = await source(registry, f"content-{name}")
        assert src and src["kind"] == kind, name
    audio = await source(registry, "content-g.Mp3")
    assert audio["stages"]["extract"]["state"] == "skipped"


async def test_office_extensions_registered(det, registry, add_folder, nas):  # PROJ-117 AK-14
    folder = await add_folder(nas / "share" / "office")
    exts = ("pptx", "docm", "dotx", "ott", "rtf", "xlsm", "ots", "csv", "pptm", "ppt", "ppsx", "pps", "odp", "otp")
    names = ["vortrag.pptx"] + [f"datei-{e}.{e}" for e in exts[1:]]
    for name in names:
        write(f"{folder}/{name}", f"content-{name}")
    await settle(det)
    for name in names:
        src = await source(registry, f"content-{name}")
        assert src and src["kind"] == "document", name
        assert src["stages"]["extract"]["state"] == "pending", name


async def test_skip_rules(det, registry, add_folder, nas, pool):  # AK-6
    folder = await add_folder(nas / "share" / "skip")
    for rel in ("@eaDir/x.jpg", "#recycle/y.pdf", ".hidden.pdf", ".git/z.pdf", "~$lock.docx", "a.tmp", "b.part",
                "c.crdownload", "Thumbs.db", "desktop.ini", "sub/.DS_Store"):
        write(f"{folder}/{rel}", f"skip-{rel}")
    write(f"{folder}/empty.pdf", b"")
    write(f"{nas}/elsewhere/link-target.pdf", "LINKED")
    os.symlink(f"{nas}/elsewhere/link-target.pdf", f"{folder}/link.pdf")
    os.symlink(f"{nas}/elsewhere", f"{folder}/linkdir")
    await settle(det)
    r = await run(det, "night")
    async with pool.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM alice.sources") == 0
    assert r["summary"]["unsupported_extensions"]["total"] == {}


# ---------------------------------------------------------------- copies and moves
async def test_copy_adds_location(det, registry, add_folder, nas, registry_service):  # AK-7, EC-2
    f1 = await add_folder(nas / "share" / "one")
    f2 = await add_folder(nas / "share" / "two")
    a = write(f"{f1}/a.pdf", "SAME")
    await settle(det)
    src = await source(registry, "SAME")
    b = write(f"{f2}/copy.pdf", "SAME")
    c = write(f"{f2}/copy2.pdf", "SAME")
    await settle(det)
    after = await source(registry, "SAME")
    assert after["id"] == src["id"] and present(after) == sorted([a, b, c])
    assert {k: v["state"] for k, v in after["stages"].items()} == {k: v["state"] for k, v in src["stages"].items()}


async def test_move_keeps_id_old_location_until_night(det, registry, add_folder, nas, repo_dir):  # AK-8, AK-9
    f1 = await add_folder(nas / "share" / "inbox")
    f2 = await add_folder(nas / "share" / "archive")
    a = write(f"{f1}/scan.pdf", "MOVE")
    for i in range(5):  # a completely emptied folder counts as "mount missing" (AK-22); 20 % limit
        write(f"{f1}/other{i}.pdf", f"STAYS{i}")
    await settle(det)
    src = await source(registry, "MOVE")
    b = f"{f2}/2026/scan-renamed.pdf"
    os.makedirs(os.path.dirname(b))
    shutil.move(a, b)
    await settle(det)
    day = await source(registry, "MOVE")
    assert day["id"] == src["id"] and present(day) == sorted([a, b]) and not day["deleted"]  # AK-9: nothing removed
    await run(det, "night")
    night = await source(registry, "MOVE")
    assert present(night) == [b] and night["path"] == src["path"] and not night["deleted"]
    assert (repo_dir / src["path"]).exists()


async def test_day_scan_never_removes(det, registry, add_folder, nas):  # AK-9
    folder = await add_folder(nas / "share" / "x")
    p = write(f"{folder}/gone.pdf", "GONE")
    await settle(det)
    os.remove(p)
    await settle(det, 3)
    src = await source(registry, "GONE")
    assert present(src) == [p] and not src["deleted"]


# ---------------------------------------------------------------- deletion
async def test_night_removes_one_of_two_locations(det, registry, add_folder, nas):  # AK-10
    folder = await add_folder(nas / "share" / "d")
    for i in range(8):
        write(f"{folder}/keep{i}.pdf", f"K{i}")
    a = write(f"{folder}/a.pdf", "TWO")
    b = write(f"{folder}/sub/b.pdf", "TWO")
    await settle(det)
    os.remove(a)
    r = await run(det, "night")
    src = await source(registry, "TWO")
    assert present(src) == [b] and not src["deleted"]
    assert r["summary"]["removed_locations"] == 1 and r["summary"]["newly_deleted"] == 0


async def test_night_deletes_source_and_moves_markdown(det, registry, add_folder, nas, repo_dir):  # AK-11
    folder = await add_folder(nas / "share" / "d")
    for i in range(8):
        write(f"{folder}/keep{i}.pdf", f"K{i}")
    p = write(f"{folder}/only.pdf", "ONLY")
    await settle(det)
    regular = (await source(registry, "ONLY"))["path"]
    os.remove(p)
    r = await run(det, "night")
    src = await source(registry, "ONLY")
    assert src["deleted"] and src["deleted_at"] and src["path"] == f"deleted/{regular}"
    assert r["summary"]["newly_deleted"] == 1
    text = (repo_dir / src["path"]).read_text()
    assert "\ndeleted: " in text and not (repo_dir / regular).exists()
    follow = git(repo_dir, "log", "--follow", "--format=%s", "--", src["path"]).strip().splitlines()
    assert len(follow) >= 2 and follow[-1].startswith("detect:")


async def test_reappearing_original_reactivates(det, registry, add_folder, nas, repo_dir):  # AK-13
    folder = await add_folder(nas / "share" / "d")
    for i in range(8):
        write(f"{folder}/keep{i}.pdf", f"K{i}")
    p = write(f"{folder}/back.pdf", "BACK")
    await settle(det)
    src = await source(registry, "BACK")
    os.remove(p)
    await run(det, "night")
    q = write(f"{folder}/other/back-again.pdf", "BACK")
    await settle(det)
    after = await source(registry, "BACK")
    assert after["id"] == src["id"] and not after["deleted"] and present(after) == [q]
    assert after["path"] == src["path"] and "deleted:" not in (repo_dir / src["path"]).read_text()
    assert after["stages"]["detect"]["state"] == "done"


# ---------------------------------------------------------------- changed in place
async def hand_title(registry_service, repo_dir, sid, title):
    src = await registry_service.get_source(sid)
    p = repo_dir / src["path"]
    text = p.read_text()
    old = next(line for line in text.splitlines() if line.startswith("title: "))
    p.write_text(text.replace(old, f"title: {title}", 1))
    await registry_service.scan()


async def test_changed_in_place_single_location(det, registry, add_folder, nas, repo_dir, registry_service):  # AK-16
    folder = await add_folder(nas / "share" / "c")
    p = write(f"{folder}/doc.pdf", "V1")
    await settle(det)
    src = await source(registry, "V1")
    for stage in ("extract", "classify"):
        items = (await registry_service.claim(stage, 10))["items"]
        await registry_service.complete(src["id"], stage, items[0]["token"])
    await hand_title(registry_service, repo_dir, src["id"], "Meine Rechnung")
    write(p, "V2-longer", mtime=os.stat(p).st_mtime + 10)
    r = await run(det, "night")
    assert r["summary"]["changed_in_place"] == 1
    after = await registry.get_source(src["id"])
    assert after["hash"] == sha("V2-longer") and after["size"] == 9 and after["title"] == "Meine Rechnung"
    assert after["stages"]["detect"]["state"] == "done"
    assert all(after["stages"][s]["state"] == "pending" for s in ("extract", "classify", "database", "rag"))
    assert await source(registry, "V1") is None


async def test_changed_in_place_with_copy(det, registry, add_folder, nas):  # AK-17
    folder = await add_folder(nas / "share" / "c")
    a = write(f"{folder}/a.pdf", "OLD")
    b = write(f"{folder}/b.pdf", "OLD")
    await settle(det)
    old = await source(registry, "OLD")
    write(a, "NEW-CONTENT", mtime=os.stat(a).st_mtime + 10)
    await run(det, "night")
    assert present(await registry.get_source(old["id"])) == [b]
    new = await source(registry, "NEW-CONTENT")
    assert new["id"] != old["id"] and present(new) == [a]


async def test_changed_in_place_to_known_hash(det, registry, add_folder, nas, repo_dir):  # AK-18
    folder = await add_folder(nas / "share" / "c")
    a = write(f"{folder}/a.pdf", "Q1")
    b = write(f"{folder}/b.pdf", "Q2")
    await settle(det)
    q1, q2 = await source(registry, "Q1"), await source(registry, "Q2")
    write(a, "Q2", mtime=os.stat(a).st_mtime + 10)
    r = await run(det, "night")
    assert present(await registry.get_source(q2["id"])) == sorted([a, b])
    q1_after = await registry.get_source(q1["id"])
    assert q1_after["deleted"] and q1_after["path"].startswith("deleted/")
    assert (repo_dir / q1_after["path"]).exists() and r["summary"]["newly_deleted"] == 1


# ---------------------------------------------------------------- watched folders
async def test_disabled_folder_frozen(det, registry, add_folder, nas, pool):  # AK-19
    folder = await add_folder(nas / "share" / "frozen")
    p = write(f"{folder}/a.pdf", "FROZEN")
    await settle(det)
    async with pool.acquire() as con:
        await con.execute("UPDATE alice.dms_watched_folders SET enabled = FALSE WHERE path = $1", folder)
    os.remove(p)
    q = write(f"{folder}/new.pdf", "NEWINFROZEN")
    await settle(det)
    await run(det, "night")
    assert present(await source(registry, "FROZEN")) == [p]
    assert await source(registry, "NEWINFROZEN") is None
    async with pool.acquire() as con:
        await con.execute("UPDATE alice.dms_watched_folders SET enabled = TRUE WHERE path = $1", folder)
    await settle(det)
    assert present(await source(registry, "NEWINFROZEN")) == [q]


async def test_folder_deleted_from_list(det, registry, add_folder, nas, pool):  # AK-20
    keep = await add_folder(nas / "share" / "keep")
    gone = await add_folder(nas / "share" / "gone")
    write(f"{keep}/k.pdf", "KEEP")
    for i in range(4):
        write(f"{gone}/g{i}.pdf", f"G{i}")
    await settle(det)
    async with pool.acquire() as con:
        await con.execute("DELETE FROM alice.dms_watched_folders WHERE path = $1", gone)
    r = await run(det, "night")  # 4 of 5 locations of the share (80 %), no limit
    for i in range(4):
        src = await source(registry, f"G{i}")
        assert src["deleted"] and present(src) == []
    assert present(await source(registry, "KEEP")) == [f"{keep}/k.pdf"]
    assert r["summary"]["removed_folders"] == [{"folder": gone, "removed_locations": 4}]
    assert r["summary"]["blocked_shares"] == []


async def test_nested_folders_longest_match(det, registry, add_folder, nas, pool):  # AK-21
    outer = await add_folder(nas / "share" / "family")
    inner = await add_folder(nas / "share" / "family" / "Steuer")
    p = write(f"{inner}/bescheid.pdf", "TAX")
    q = write(f"{outer}/brief.pdf", "LETTER")
    await settle(det)
    await run(det, "night")
    assert present(await source(registry, "TAX")) == [p]
    async with pool.acquire() as con:
        rows = {r["path"]: r["folder"] for r in await con.fetch("SELECT path, folder FROM alice.detect_files")}
    assert rows == {p: inner, q: outer}


async def test_nested_folder_added_later_reassigns(det, registry, add_folder, nas, pool):  # AK-21
    outer = await add_folder(nas / "share" / "family")
    p = write(f"{outer}/Steuer/bescheid.pdf", "TAX")
    await settle(det)
    inner = await add_folder(nas / "share" / "family" / "Steuer")
    await run(det, "night")
    async with pool.acquire() as con:
        assert await con.fetchval("SELECT folder FROM alice.detect_files WHERE path = $1", p) == inner
    assert present(await source(registry, "TAX")) == [p]


async def test_renamed_folder_keeps_sources(det, registry, add_folder, nas, pool):  # EC-6
    old = await add_folder(nas / "share" / "old")
    for i in range(3):
        write(f"{old}/f{i}.pdf", f"R{i}")
    await settle(det)
    ids = [(await source(registry, f"R{i}"))["id"] for i in range(3)]
    new = str(nas / "share" / "new")
    os.rename(old, new)
    async with pool.acquire() as con:
        await con.execute("UPDATE alice.dms_watched_folders SET path = $2 WHERE path = $1", old, new)
    r = await run(det, "night")
    for i in range(3):
        src = await source(registry, f"R{i}")
        assert src["id"] == ids[i] and not src["deleted"] and present(src) == [f"{new}/f{i}.pdf"]
    assert r["summary"]["new_sources"] == 0 and r["summary"]["newly_deleted"] == 0


# ---------------------------------------------------------------- safeguards
async def test_unreadable_or_empty_folder_skipped(det, registry, add_folder, nas):  # AK-22
    folder = await add_folder(nas / "share" / "mount")
    write(f"{folder}/a.pdf", "MOUNTED")
    await settle(det)
    os.rename(folder, folder + ".away")  # mount missing: folder not readable
    r = await run(det, "night")
    assert present(await source(registry, "MOUNTED")) == [f"{folder}/a.pdf"]
    assert r["summary"]["skipped_folders"][0]["folder"] == folder and folder in det.warnings
    os.makedirs(folder)  # empty mount point
    r = await run(det, "night")
    assert present(await source(registry, "MOUNTED")) == [f"{folder}/a.pdf"]
    assert "leer" in r["summary"]["skipped_folders"][0]["reason"]
    os.rmdir(folder)
    os.rename(folder + ".away", folder)  # back
    b = write(f"{folder}/b.pdf", "AFTER")
    await settle(det)
    r = await run(det, "night")
    assert r["summary"]["skipped_folders"] == [] and folder not in det.warnings
    assert present(await source(registry, "AFTER")) == [b]


async def test_unreadable_subfolder_protected(det, registry, add_folder, nas):
    folder = await add_folder(nas / "share" / "p")
    for i in range(9):
        write(f"{folder}/k{i}.pdf", f"P{i}")
    write(f"{folder}/locked/x.pdf", "LOCKED")
    await settle(det)
    os.chmod(f"{folder}/locked", 0)
    try:
        r = await run(det, "night")
        assert present(await source(registry, "LOCKED")) == [f"{folder}/locked/x.pdf"]
        assert any(p["path"] == f"{folder}/locked" for p in r["summary"]["problems"]["items"])
    finally:
        os.chmod(f"{folder}/locked", 0o755)


@pytest.mark.parametrize("missing,blocked", [(5, True), (3, False)])  # 25 % / 15 % of 20
async def test_deletion_limit_per_share(det, registry, add_folder, nas, missing, blocked):  # AK-23
    a = await add_folder(nas / "share1" / "a")
    b = await add_folder(nas / "share1" / "b")
    other = await add_folder(nas / "share2" / "c")
    paths = [write(f"{a if i < 10 else b}/f{i}.pdf", f"F{i}") for i in range(20)]
    o = write(f"{other}/o.pdf", "OTHER")
    write(f"{other}/o2.pdf", "OTHER2")
    await settle(det)
    for p in paths[8:8 + missing]:  # spread over both folders of share1
        os.remove(p)
    os.remove(o)  # share2: 1 of 2 missing → blocked as well
    r = await run(det, "night")
    removed = [not present(await source(registry, f"F{i}")) for i in range(8, 8 + missing)]
    shares = {s["share"]: s for s in r["summary"]["blocked_shares"]}
    assert str(nas / "share2") in shares
    if blocked:
        assert not any(removed) and shares[str(nas / "share1")]["missing"] == 5
        assert shares[str(nas / "share1")]["percent"] == 25.0
    else:
        assert all(removed) and str(nas / "share1") not in shares
        assert r["summary"]["removed_locations"] == 3


async def test_unreadable_file_is_problem_until_readable(det, registry, add_folder, nas):  # AK-24
    folder = await add_folder(nas / "share" / "r")
    p = write(f"{folder}/secret.pdf", "SECRET")
    os.chmod(p, 0)
    try:
        await settle(det)
        items, count = await det.problems()
        assert count == 1 and items[0]["path"] == p and items[0]["cause"] == "Keine Leserechte"
        assert items[0]["first_seen"] and items[0]["last_seen"]
        first = items[0]["first_seen"]
        await run(det)
        items, _ = await det.problems()
        assert items[0]["first_seen"] == first and items[0]["last_seen"] >= first
        r = await run(det, "night")
        assert r["summary"]["problems"]["count"] == 1
    finally:
        os.chmod(p, 0o644)
    await run(det)
    assert present(await source(registry, "SECRET")) == [p]
    assert (await det.problems())[1] == 0


async def test_register_unavailable_pauses(make_detector, registry, add_folder, nas):  # AK-25
    import httpx

    from app.registry import RegistryClient

    def refuse(request):
        raise httpx.ConnectError("connection refused")

    down = RegistryClient("http://registry", client=httpx.AsyncClient(transport=httpx.MockTransport(refuse),
                                                                      base_url="http://registry"))
    folder = await add_folder(nas / "share" / "u")
    d = make_detector(down)
    await run(d)
    p = write(f"{folder}/during.pdf", "DURING")
    await run(d)
    r = await run(d)
    assert r["state"] == "paused" and d.paused_reason
    r = await run(d, "night")
    assert r["state"] == "paused" and r["summary"]["removed_locations"] == 0
    up = make_detector(registry)
    await settle(up)
    assert present(await source(registry, "DURING")) == [p]


async def test_no_parallel_runs(det, add_folder, nas):  # AK-26
    from app.detector import Busy

    await add_folder(nas / "share" / "x")
    task = det.start("night")
    with pytest.raises(Busy):
        det.start("day")
    with pytest.raises(Busy):
        det.start("night")
    await det.tick()  # scheduler does not start a second run either
    assert (await task)["state"] == "done"
    assert (await run(det))["state"] == "done"


async def test_interrupted_night_no_duplicates(make_detector, registry, add_folder, nas, pool):  # AK-27
    class Crashing:
        def __init__(self, inner, after):
            self.inner, self.after, self.n = inner, after, 0

        def __getattr__(self, name):
            return getattr(self.inner, name)

        async def register(self, **kw):
            self.n += 1
            if self.n > self.after:
                raise RuntimeError("service restarted")
            return await self.inner.register(**kw)

    f1 = await add_folder(nas / "share" / "a")
    f2 = await add_folder(nas / "share" / "b")
    for i in range(10):
        write(f"{f1}/f{i}.pdf", f"I{i}")
        write(f"{f2}/copy{i}.pdf", f"I{i}")
    r = await run(make_detector(Crashing(registry, 7)), "night")
    assert r["state"] == "failed"
    async with pool.acquire() as con:  # a run left behind as 'running' by a crash
        await con.execute("INSERT INTO alice.detect_runs (kind, state, started_at) VALUES ('night', 'running', NOW())")
    d = make_detector(registry)
    assert await d.mark_aborted() == 1
    r = await run(d, "night")
    assert r["state"] == "done"
    async with pool.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM alice.sources") == 10
        assert await con.fetchval("SELECT count(*) FROM alice.source_locations WHERE present") == 20
        assert await con.fetchval("SELECT count(*) FROM alice.detect_files") == 20


# ---------------------------------------------------------------- first run and summary
async def test_first_run_registers_inventory(det, registry, add_folder, nas, repo_dir, pool, caplog):  # AK-28
    folder = await add_folder(nas / "share" / "inventory")
    for i in range(1200):
        write(f"{folder}/{i // 100:02d}/file{i:04d}.pdf", f"INV{i}")
    caplog.set_level(logging.INFO, logger="alice-file-detection")
    r = await run(det, "night")
    assert r["state"] == "done" and r["summary"]["new_sources"] == 1200
    async with pool.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM alice.sources") == 1200
        assert await con.fetchval("SELECT count(*) FROM alice.source_stages WHERE stage = 'detect' "
                                  "AND state = 'done'") == 1200
    commits = git(repo_dir, "log", "--format=%s").strip().splitlines()
    batches = [c for c in commits if c.startswith("rebuild: detect")]
    assert len(batches) == 3 and all(int(c.split()[2]) <= 500 for c in batches)
    assert sum(int(c.split()[2]) for c in batches) == 1200
    assert git(repo_dir, "status", "--porcelain").strip() == ""
    assert "Nightly run: 500 new files registered so far" in caplog.text


async def test_summary_counts_unsupported_extensions(det, registry, add_folder, nas, pool):  # AK-29
    f1 = await add_folder(nas / "share" / "one")
    f2 = await add_folder(nas / "share" / "two")
    for i in range(2):
        write(f"{f1}/a{i}.zip", f"zip{i}")
    write(f"{f2}/a.zip", "zip-2")
    write(f"{f2}/b.EXE", "exe")
    write(f"{f2}/README", "noext")
    write(f"{f1}/doc.pdf", "SUPPORTED")
    r = await run(det, "night")
    s = r["summary"]
    assert s["unsupported_extensions"]["total"] == {"(ohne)": 1, "exe": 1, "zip": 3}
    assert s["unsupported_extensions"]["per_folder"] == {f1: {"zip": 2}, f2: {"(ohne)": 1, "exe": 1, "zip": 1}}
    for key in ("duration_seconds", "files_scanned", "dirs_scanned", "new_sources", "new_locations",
                "removed_locations", "newly_deleted", "reactivated", "changed_in_place", "skipped_folders",
                "blocked_shares", "removed_folders", "problems"):
        assert key in s
    assert s["files_scanned"] == 6 and s["new_sources"] == 1
    async with pool.acquire() as con:
        row = await con.fetchrow("SELECT state, summary FROM alice.detect_runs WHERE id = $1", r["id"])
    assert row["state"] == "done" and '"zip": 3' in row["summary"]


async def test_summaries_kept_for_retention(det, add_folder, nas, pool):
    await add_folder(nas / "share" / "x")
    async with pool.acquire() as con:
        await con.execute("INSERT INTO alice.detect_runs (kind, state, started_at) VALUES "
                          "('night', 'done', NOW() - interval '29 days'), ('night', 'done', NOW() - interval '200 days')")
    await run(det, "night")
    async with pool.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM alice.detect_runs") == 2


async def test_originals_untouched(det, registry, add_folder, nas):  # AK-31
    folder = await add_folder(nas / "share" / "orig")
    files = [write(f"{folder}/ä ö ü ß – sonder & zeichen #{i}/{'x' * 120}{i}.pdf", f"O{i}") for i in range(3)]  # EC-5
    before = {p: (os.stat(p).st_mtime_ns, os.stat(p).st_size, sha(f"O{i}")) for i, p in enumerate(files)}
    await settle(det)
    await run(det, "night")
    for i, p in enumerate(files):
        assert (os.stat(p).st_mtime_ns, os.stat(p).st_size, fsscan.sha256_file(p)) == before[p]
        assert present(await source(registry, f"O{i}")) == [p]


async def test_invalid_utf8_name_is_problem_not_failure(det, registry, add_folder, nas):  # EC-5
    folder = await add_folder(nas / "share" / "enc")
    ok = write(f"{folder}/gut.pdf", "GOOD")
    with open(os.fsencode(folder) + b"/kaputt_\xe4.pdf", "wb") as f:
        f.write(b"latin1")
    os.makedirs(os.fsencode(folder) + b"/ordner_\xfc")
    await settle(det)
    r = await run(det, "night")
    assert r["state"] == "done" and present(await source(registry, "GOOD")) == [ok]
    causes = sorted(p["cause"] for p in r["summary"]["problems"]["items"])
    assert causes == ["Dateiname ist kein gültiges UTF-8", "Ordnername ist kein gültiges UTF-8"]
    os.remove(os.fsencode(folder) + b"/kaputt_\xe4.pdf")
    r = await run(det, "night")
    assert [p["cause"] for p in r["summary"]["problems"]["items"]] == ["Ordnername ist kein gültiges UTF-8"]


async def test_file_vanishes_while_hashing(det, registry, add_folder, nas, monkeypatch):  # EC-1
    folder = await add_folder(nas / "share" / "v")
    p = write(f"{folder}/flüchtig.pdf", "VANISH")
    await run(det)
    real = fsscan.sha256_file

    def vanish(path):
        if path == p:
            os.remove(path)
        return real(path)

    monkeypatch.setattr(fsscan, "sha256_file", vanish)
    r = await run(det)
    assert r["state"] == "done" and await source(registry, "VANISH") is None
    assert (await det.problems())[1] == 0


async def test_rename_and_change_at_once(det, registry, add_folder, nas):  # EC-3
    folder = await add_folder(nas / "share" / "rc")
    for i in range(9):
        write(f"{folder}/k{i}.pdf", f"RC{i}")
    a = write(f"{folder}/alt.pdf", "OLDTEXT")
    await settle(det)
    old = await source(registry, "OLDTEXT")
    os.remove(a)
    b = write(f"{folder}/neu.pdf", "NEWTEXT")
    await settle(det)
    await run(det, "night")
    new = await source(registry, "NEWTEXT")
    assert new["id"] != old["id"] and present(new) == [b]
    assert (await registry.get_source(old["id"]))["deleted"]


async def test_broken_pdf_is_registered(det, registry, add_folder, nas):  # EC-7
    folder = await add_folder(nas / "share" / "b")
    p = write(f"{folder}/kaputt.pdf", b"\x00\x01 not a pdf")
    await settle(det)
    assert present(await source(registry, b"\x00\x01 not a pdf")) == [p]
