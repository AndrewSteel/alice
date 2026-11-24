"""Level 1 of the reconciliation (PROJ-120): NAS <-> register check, registering missing files,
rolling re-hash, applying differing hashes, lease against the nightly run. Real register + temporary
git repo + throwaway PostgreSQL, temporary folders as NAS."""
import os
import time

import httpx
import pytest

from app import main, reconcile
from app.detector import Busy

from .conftest import run
from .test_detection import sha, source, write


async def night(det):
    r = await run(det, "night")
    assert r["state"] == "done", r


async def test_check_finds_unregistered_and_missing(det, registry, add_folder, nas):  # AK-23, AK-24
    folder = await add_folder(nas / "share" / "docs")
    write(f"{folder}/a.pdf", "A")
    gone = write(f"{folder}/b.pdf", "B")
    await night(det)
    new = write(f"{folder}/sub/c.pdf", "C")
    write(f"{folder}/notes.xyz", "ignored")  # extension not processed
    os.remove(gone)
    out = await reconcile.check(det)
    assert [u["path"] for u in out["unregistered"]] == [new]
    assert [(m["path"], m["source_id"]) for m in out["missing"]] == [(gone, (await source(registry, "B"))["id"])]
    assert out["skipped_folders"] == []
    # check changes nothing
    assert await source(registry, "C") is None
    assert (await source(registry, "B"))["locations"][0]["present"] is True
    res = await reconcile.register(det, [{"path": new}])
    assert res["results"][0]["registered"] and res["new_sources"] == 1
    src = await source(registry, "C")
    assert src and res["results"][0]["source_id"] == src["id"]
    assert src["stages"]["detect"]["state"] == "done"
    out = await reconcile.check(det)
    assert out["unregistered"] == [] and len(out["missing"]) == 1  # missing stays reported only


async def test_skipped_and_disabled_folders(det, registry, add_folder, nas):  # AK-42, EC-8
    a = await add_folder(nas / "share" / "a")
    b = await add_folder(nas / "other" / "b")
    write(f"{a}/1.pdf", "1")
    write(f"{b}/2.pdf", "2")
    await night(det)
    for f in os.listdir(a):
        os.remove(os.path.join(a, f))  # empty although files are known: mount missing
    async with det.pool.acquire() as con:
        await con.execute("UPDATE alice.dms_watched_folders SET enabled = FALSE WHERE path = $1", b)
    os.remove(f"{b}/2.pdf")
    out = await reconcile.check(det)
    assert out["missing"] == [] and out["unregistered"] == []
    assert [s["folder"] for s in out["skipped_folders"]] == [a]


async def test_rolling_rehash_thirds(det, registry, add_folder, nas):  # AK-36
    folder = await add_folder(nas / "share" / "r")
    paths = [write(f"{folder}/{i}.pdf", f"content-{i:02d}" * 10) for i in range(9)]
    await night(det)
    seen = []
    for _ in range(3):
        out = await reconcile.rehash(det, cycle_days=3)
        assert out["mismatches"] == [] and out["hashed"] > 0
        seen.append(out["hashed"])
    assert sum(seen) == 9 and out["cycle"]["done"] == 9 and out["cycle"]["percent"] == 100.0
    async with det.pool.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM alice.detect_files WHERE rehashed_at IS NULL") == 0
    again = await reconcile.rehash(det, cycle_days=3)  # cycle complete and not yet due: nothing twice
    assert again["hashed"] == 0
    async with det.pool.acquire() as con:  # cycle older than its duration: next cycle starts
        await con.execute("UPDATE alice.detect_hash_cycle SET started_at = NOW() - interval '4 days'")
    assert (await reconcile.rehash(det, cycle_days=3))["hashed"] > 0
    assert len(paths) == 9


async def test_rehash_continues_after_interruption(det, registry, add_folder, nas):  # AK-37
    folder = await add_folder(nas / "share" / "r")
    for i in range(6):
        write(f"{folder}/{i}.pdf", f"x{i}" * 50)
    await night(det)
    first = await reconcile.rehash(det, max_bytes=1)  # "interrupted" after the first file
    assert first["hashed"] == 1
    det2 = type(det)(det.s, det.pool, det.registry)  # restart: new instance, state from the DB
    rest = await reconcile.rehash(det2, full=False, cycle_days=1)
    assert rest["hashed"] == 5 and rest["cycle"]["done"] == 6


async def test_same_size_and_mtime_changed_content(det, registry, add_folder, nas):  # AK-25
    folder = await add_folder(nas / "share" / "c")
    p = write(f"{folder}/doc.pdf", "AAAA", mtime=1_700_000_000)
    await night(det)
    sid = (await source(registry, "AAAA"))["id"]
    write(p, "BBBB", mtime=1_700_000_000)  # same size and mtime: the nightly run cannot see it
    await night(det)
    assert (await source(registry, "AAAA"))["id"] == sid
    out = await reconcile.rehash(det, full=True)
    assert out["mismatches"] == [{"path": p, "source_id": sid, "hash": sha("BBBB")}]
    assert (await source(registry, "AAAA"))["id"] == sid  # rehash itself changes nothing
    res = await reconcile.apply(det, [p])
    assert res["results"][0]["applied"]
    src = await registry.get_source(sid)
    assert src["hash"] == sha("BBBB") and src["stages"]["extract"]["state"] == "pending"


async def test_rehash_hash_of_other_source(det, registry, add_folder, nas):  # EC-9
    folder = await add_folder(nas / "share" / "c")
    p = write(f"{folder}/a.pdf", "AAAA", mtime=1_700_000_000)
    write(f"{folder}/b.pdf", "BBBB")
    await night(det)
    a = (await source(registry, "AAAA"))["id"]
    write(p, "BBBB", mtime=1_700_000_000)
    out = await reconcile.rehash(det, full=True)
    await reconcile.apply(det, [m["path"] for m in out["mismatches"]])
    b = await source(registry, "BBBB")
    assert p in [loc["path"] for loc in b["locations"] if loc["present"]]
    assert (await registry.get_source(a))["deleted"] is True


async def test_unreadable_file_reported_and_retried(det, registry, add_folder, nas, monkeypatch):  # AK-43
    folder = await add_folder(nas / "share" / "u")
    p = write(f"{folder}/locked.pdf", "LOCKED")
    await night(det)
    real = reconcile.fsscan.sha256_file

    def denied(path):
        if path == p:
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(reconcile.fsscan, "sha256_file", denied)
    out = await reconcile.rehash(det, full=True)
    assert [u["path"] for u in out["unreadable"]] == [p] and out["cycle"]["done"] == 0
    assert (await source(registry, "LOCKED"))["stages"]["extract"]["state"] == "pending"
    monkeypatch.setattr(reconcile.fsscan, "sha256_file", real)
    out = await reconcile.rehash(det, cycle_days=30)  # next run tries it again
    assert out["hashed"] == 1 and out["cycle"]["done"] == 1


async def test_unreadable_file_does_not_hold_cycle_open(det, registry, add_folder, nas, monkeypatch):  # AK-36, AK-43
    folder = await add_folder(nas / "share" / "u")
    bad = write(f"{folder}/a-locked.pdf", "LOCKED")
    for i in range(4):
        write(f"{folder}/{i}.pdf", f"ok-{i}" * 10)
    await night(det)
    real = reconcile.fsscan.sha256_file

    def denied(path):
        if path == bad:
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(reconcile.fsscan, "sha256_file", denied)
    out = await reconcile.rehash(det, cycle_days=3, max_bytes=10**9)
    assert out["cycle"]["done"] == 4 and out["cycle"]["total"] == 5
    async with det.pool.acquire() as con:  # cycle overdue, one file never hashable
        await con.execute("UPDATE alice.detect_hash_cycle SET started_at = NOW() - interval '4 days'")
    out = await reconcile.rehash(det, cycle_days=3)
    # a new cycle started anyway; the unreadable file is reported again, the others are hashed again
    assert [u["path"] for u in out["unreadable"]] == [bad]
    assert out["hashed"] > 0 and out["cycle"]["done"] == out["hashed"]


async def test_large_file_hashed_whole(det, registry, add_folder, nas):  # EC-10
    folder = await add_folder(nas / "share" / "big")
    write(f"{folder}/big.pdf", b"x" * (3 * 1024 * 1024))
    write(f"{folder}/small.pdf", "s")
    await night(det)
    out = await reconcile.rehash(det, max_bytes=10)  # budget far below the file size
    assert out["hashed"] == 1 and out["mismatches"] == []
    out = await reconcile.rehash(det, max_bytes=10)
    assert out["hashed"] == 1  # the rest in the next portion


async def test_lease_blocks_nightly_and_vice_versa(make_detector, registry, add_folder, nas):  # AK-35
    det = make_detector(registry, catchup_hours=25)  # the last nightly slot is always due
    await add_folder(nas / "share" / "l")
    token = reconcile.acquire_lease(det, None, 60)
    assert await det.nightly_due() is not None
    await det.tick()
    assert det.running is None  # due, but held back by the lease
    with pytest.raises(reconcile.LeaseHeld):
        reconcile.acquire_lease(det, None, 60)
    assert reconcile.acquire_lease(det, token, 60) == token  # renewal
    reconcile.release_lease(det, token)
    await det.tick()
    assert det.running == "night"
    with pytest.raises(Busy):
        reconcile.acquire_lease(det, None, 60)
    await det.task
    det.lease = ("x" * 32, time.monotonic() - 1)  # expired lease does not block
    assert reconcile.acquire_lease(det, None, 60) != "x" * 32


async def test_http_interface(det, registry, add_folder, nas):
    folder = await add_folder(nas / "share" / "h")
    write(f"{folder}/a.pdf", "A")
    main.app.state.det = det
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://d") as c:
        r = await c.post("/reconcile/lease", json={"seconds": 60})
        token = r.json()["token"]
        assert (await c.post("/reconcile/lease", json={"seconds": 60})).status_code == 409
        out = (await c.post("/reconcile/check")).json()
        assert [u["path"] for u in out["unregistered"]] == [f"{folder}/a.pdf"]
        r = await c.post("/reconcile/register", json={"items": [{"path": f"{folder}/a.pdf"}]})
        assert r.json()["results"][0]["registered"]
        r = await c.post("/reconcile/rehash", json={"full": True})
        assert r.json()["hashed"] == 1
        assert (await c.post("/reconcile/apply", json={"paths": []})).status_code == 422
        assert (await c.delete(f"/reconcile/lease/{token}")).json() == {"released": True}
