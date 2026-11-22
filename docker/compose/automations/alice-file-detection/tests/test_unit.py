"""Configuration, file system rules, schedule, the 10,000-files day scan and the interface."""
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import fsscan
from app.config import Settings, extension_map

from .conftest import run


# ---------------------------------------------------------------- config + rules
def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("DETECT_EXT_DOCUMENT", "pdf, TXT")
    monkeypatch.setenv("DETECT_SKIP_FILES", "*.bak")
    monkeypatch.setenv("DETECT_NIGHTLY_TIME", "03:30")
    monkeypatch.setenv("DETECT_DELETE_LIMIT_PERCENT", "10")
    monkeypatch.setenv("DETECT_SUMMARY_RETENTION_DAYS", "7")
    s = Settings.from_env()
    assert s.extensions["txt"] == "document" and "docx" not in s.extensions and s.extensions["jpg"] == "image"
    assert s.skip_files == ["*.bak"] and s.nightly.hour == 3 and s.nightly.minute == 30
    assert s.delete_limit_percent == 10 and s.retention_days == 30  # at least 30 days


def test_defaults():
    s = Settings()
    assert s.scan_interval_seconds == 300 and s.nightly_time == "02:00" and s.catchup_hours == 6
    assert s.delete_limit_percent == 20
    assert extension_map({"video": ".MP4"}) == {"mp4": "video"}


@pytest.mark.parametrize("name,kind", [("a.PDF", "document"), ("b.xlsx", "document"), ("c.Jpeg", "image"),
                                       ("d.m4a", "audio"), ("e.MKV", "video"), ("f.zip", None), ("noext", None)])
def test_kind_of(name, kind):
    assert fsscan.kind_of(name, Settings()) == kind


@pytest.mark.parametrize("name,skipped", [(".hidden.pdf", True), ("~$doc.docx", True), ("x.TMP", True),
                                          ("y.part", True), ("z.crdownload", True), ("thumbs.db", True),
                                          ("Desktop.ini", True), ("ok.pdf", False), ("a~$b.pdf", False)])
def test_skip_file(name, skipped):
    assert fsscan.skip_file(name, Settings()) is skipped


def test_skip_dir():
    s = Settings()
    assert fsscan.skip_dir("@eaDir", s) and fsscan.skip_dir("#recycle", s) and fsscan.skip_dir(".git", s)
    assert not fsscan.skip_dir("Steuer", s)


def test_share_of():
    assert fsscan.share_of("/mnt/nas/family/a/b.pdf", "/mnt/nas", "/mnt/nas/family/a") == "/mnt/nas/family"
    assert fsscan.share_of("/data/x/b.pdf", "/mnt/nas", "/data/x") == "/data/x"


def test_under():
    assert fsscan.under("/a/b/c", "/a/b") and fsscan.under("/a/b", "/a/b/")
    assert not fsscan.under("/a/bc", "/a/b")


def test_large_file_hashed_in_chunks(tmp_path, monkeypatch):  # EC-4
    monkeypatch.setattr(fsscan, "HASH_CHUNK", 7)
    p = tmp_path / "big.bin"
    p.write_bytes(os.urandom(1000))
    import hashlib

    assert fsscan.sha256_file(str(p)) == "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def test_no_redis_or_weaviate():  # AK-31: the old system's stores are never touched
    import pathlib

    code = "".join(p.read_text() for p in pathlib.Path(fsscan.__file__).parent.glob("*.py")).lower()
    assert "redis" not in code and "weaviate" not in code
    assert '"rb"' in code and '"wb"' not in code and "os.remove" not in code and "unlink" not in code


def test_no_nginx_route():  # AK-30
    import pathlib

    nginx = pathlib.Path(__file__).resolve().parents[3] / "infra" / "nginx"
    text = "".join(p.read_text(errors="ignore") for p in nginx.rglob("*") if p.is_file())
    assert nginx.is_dir() and "8013" not in text and "file-detection" not in text


# ---------------------------------------------------------------- schedule
async def test_nightly_due_and_catchup(make_detector, pool):  # AK-27
    det = make_detector(None, nightly_time="02:00", timezone="UTC", catchup_hours=6)
    slot = datetime(2026, 11, 22, 2, 0, tzinfo=timezone.utc)
    assert det.nightly_slot(slot + timedelta(hours=1)) == slot
    assert det.nightly_slot(slot - timedelta(minutes=1)) == slot - timedelta(days=1)
    assert await det.nightly_due(slot + timedelta(minutes=1)) == "schedule"
    assert await det.nightly_due(slot + timedelta(hours=7)) is None  # too late: next night takes over
    async with pool.acquire() as con:
        await con.execute("INSERT INTO alice.detect_runs (kind, state, started_at) VALUES ('night', 'aborted', $1)",
                          slot + timedelta(minutes=5))
    assert await det.nightly_due(slot + timedelta(hours=2)) == "catchup"
    async with pool.acquire() as con:
        await con.execute("INSERT INTO alice.detect_runs (kind, state, started_at) VALUES ('night', 'done', $1)",
                          slot + timedelta(hours=1))
    assert await det.nightly_due(slot + timedelta(hours=2)) is None


# ---------------------------------------------------------------- AK-4 with a fake register
class FakeRegistry:
    """Just enough register for the day scan; keeps alice.sources rows for the foreign key."""

    def __init__(self, pool=None):
        self.pool = pool
        self.by_hash_map: dict[str, str] = {}
        self.calls = 0

    async def register(self, *, kind, hash, title, path, size, modified, batch=False):
        self.calls += 1
        created = hash not in self.by_hash_map
        sid = self.by_hash_map.setdefault(hash, f"{len(self.by_hash_map):012d}")
        if created and self.pool:
            async with self.pool.acquire() as con:
                await con.execute("INSERT INTO alice.sources (id, kind, hash, title, path) VALUES ($1, $2, $3, $4, $5)",
                                  sid, kind, hash, title, f"documents/{sid}.md")
        return {"id": sid, "created": created, "reactivated": False}

    async def flush(self):
        pass


async def test_unchanged_tree_not_listed_or_hashed(make_detector, pool, nas, add_folder, monkeypatch):  # AK-4
    folder = await add_folder(nas / "share" / "big")
    for d in range(100):
        os.makedirs(f"{folder}/d{d:03d}/sub")
        for i in range(100):
            sub = "/sub" if i % 2 else ""
            with open(f"{folder}/d{d:03d}{sub}/f{i:03d}.pdf", "w") as f:
                f.write(f"{d}-{i}")
    reg = FakeRegistry(pool)
    det = make_detector(reg)
    for _ in range(3):  # wait, register, confirm the directory times
        await run(det)
    async with pool.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM alice.detect_files") == 10000
    counts = {"list": 0, "hash": 0}
    real_list, real_hash = fsscan.list_dir, fsscan.sha256_file

    def counting_list(path):
        counts["list"] += 1
        return real_list(path)

    def counting_hash(path):
        counts["hash"] += 1
        return real_hash(path)

    monkeypatch.setattr(fsscan, "list_dir", counting_list)
    monkeypatch.setattr(fsscan, "sha256_file", counting_hash)
    calls = reg.calls
    r = await run(det)
    assert r["state"] == "done" and counts == {"list": 0, "hash": 0} and reg.calls == calls
    assert r["summary"]["dirs_scanned"] == 201 and r["summary"]["dirs_listed"] == 0
    # one new file: only its directory is listed, only it is hashed
    with open(f"{folder}/d042/sub/new.pdf", "w") as f:
        f.write("new")
    await run(det)
    await run(det)
    assert counts["hash"] == 1 and counts["list"] == 2  # changed dir, then its confirmation


# ---------------------------------------------------------------- interface
async def test_api_trigger_busy_and_runs(make_detector, pool, nas, add_folder):  # AK-26, AK-30
    from app import main

    await add_folder(nas / "share" / "api")
    det = make_detector(FakeRegistry())
    main.app.state.det = det
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = await c.get("/health")
        assert r.status_code == 200 and r.json()["status"] == "healthy"
        r = await c.post("/runs/night")
        assert r.status_code == 202 and r.json() == {"started": "night"}
        r = await c.post("/runs/day")
        assert r.status_code == 409 and r.json()["error"] == "busy"
        await det.task
        assert (await c.post("/runs/bogus")).status_code == 404
        runs = (await c.get("/runs", params={"kind": "night"})).json()["runs"]
        assert len(runs) == 1 and runs[0]["state"] == "done" and runs[0]["trigger"] == "manual"
        assert runs[0]["summary"]["kind"] == "night"
        one = (await c.get(f"/runs/{runs[0]['id']}")).json()
        assert one["id"] == runs[0]["id"]
        assert (await c.get("/runs/999999")).status_code == 404
        assert (await c.get("/problems")).json() == {"count": 0, "items": []}
        det.warnings["/x"] = "nicht lesbar"
        body = (await c.get("/health")).json()
        assert body["status"] == "warning" and "/x" in body["warnings"][0]


async def test_health_unhealthy_when_scheduler_stalls(make_detector, pool):
    from app import main

    det = make_detector(FakeRegistry())
    det.last_tick -= 1000
    main.app.state.det = det
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 503 and r.json()["status"] == "unhealthy"




async def test_scheduled_day_scans_wait_for_first_nightly_run(make_detector, pool, nas, add_folder):  # AK-28
    await add_folder(nas / "share" / "x")
    det = make_detector(FakeRegistry(pool), nightly_time="02:00", catchup_hours=0)
    await det.tick()
    assert det.task is None  # no nightly due, inventory not yet registered: no day scan either
    await det.start("night", "manual")
    det.last_day_start = float("-inf")
    await det.tick()
    assert det.task is not None and det.running == "day"
    assert (await det.task)["state"] == "done"


async def test_many_new_files_in_day_scan_use_batch(make_detector, pool, nas, add_folder):
    folder = await add_folder(nas / "share" / "many")
    reg = FakeRegistry(pool)
    batches = []
    orig = reg.register

    async def register(**kw):
        batches.append(kw["batch"])
        return await orig(**kw)

    flushed = []

    async def flush():
        flushed.append(True)

    reg.register, reg.flush = register, flush
    det = make_detector(reg)
    await run(det)
    for i in range(25):
        with open(f"{folder}/f{i}.pdf", "w") as f:
            f.write(str(i))
    await run(det)
    await run(det)
    assert len(batches) == 25 and all(batches) and flushed
