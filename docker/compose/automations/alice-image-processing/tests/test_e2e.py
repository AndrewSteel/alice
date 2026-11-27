"""End to end: the real register code (alice-source-registry, loaded in-process) with a throwaway
PostgreSQL (incl. the PROJ-125 migration) and a temporary git repo; the image worker talks to it over its
HTTP interface, to the fake gateway, fake Geoapify and fake old Weaviate, and keeps its own state in the
same PostgreSQL. Skipped without TEST_POSTGRES_DSN (scripts/test-services.sh sets it)."""
import asyncio
import importlib.util
import os
import pathlib
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.registry import RegistryClient
from app.store import Store
from app.worker import Describer, Locator

from .conftest import LONG_DESCRIPTION, make_image

DSN = os.environ.get("TEST_POSTGRES_DSN")
ROOT = pathlib.Path(__file__).resolve().parents[5]
REGISTRY_DIR = ROOT / "docker" / "compose" / "automations" / "alice-source-registry" / "app"
MIGRATION = ROOT / "sql" / "migrations" / "2026-11-27_PROJ-125_images.sql"
OCT = datetime(2026, 10, 14, 7, 32, 11, tzinfo=timezone.utc)  # 09.32.11 in Berlin
RIMINI = (44.0596, 12.5683, 3.5)


def _load_registry():
    if "registry_app" not in sys.modules:
        spec = importlib.util.spec_from_file_location("registry_app", REGISTRY_DIR / "__init__.py",
                                                      submodule_search_locations=[str(REGISTRY_DIR)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["registry_app"] = mod
        spec.loader.exec_module(mod)
    import registry_app.config as rconfig
    import registry_app.main as rmain
    import registry_app.service as rservice
    return rmain, rconfig, rservice


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "safe.directory=*", *args], capture_output=True,
                          text=True, check=True).stdout


class Env:
    pass


@pytest.fixture
async def env(tmp_path, settings, vision, geoapify, weaviate, nas):
    if not DSN:
        pytest.skip("TEST_POSTGRES_DSN not set")
    import asyncpg

    rmain, rconfig, rservice = _load_registry()
    pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=10)
    async with pool.acquire() as con:
        await con.execute(MIGRATION.read_text())
        await con.execute("TRUNCATE alice.sources CASCADE")
        await con.execute("TRUNCATE alice.image_processing_state, alice.image_geocode_usage, "
                          "alice.image_describe_requests")
    repo = tmp_path / "sot"
    repo.mkdir()
    reg = rservice.Registry(rconfig.Settings(repo_path=str(repo), postgres_dsn=DSN), pool, None)
    await reg.startup()
    rmain.app.state.reg = reg
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=rmain.app), base_url="http://registry")
    client = RegistryClient("http://registry", client=http)

    e = Env()
    e.reg, e.repo, e.pool, e.client, e.nas, e.settings = reg, repo, pool, client, nas, settings
    e.store = Store(pool)
    e.counter = 0

    def workers(**overrides):
        for k, v in overrides.items():
            setattr(settings, k, v)
        e.describer = Describer(settings, client, e.store, vision)
        e.locator = Locator(settings, client, e.store, weaviate, geoapify, e.describer)
        if not settings.location_takeover:
            e.locator.weaviate = None
        return e.describer, e.locator

    async def register(name=None, kind="image", modified=OCT, **img):
        e.counter += 1
        name = name or f"IMG_{e.counter}.jpg"
        path = nas / name
        if kind == "image" and not path.exists():
            make_image(path, **img)
        elif kind != "image":
            path.write_text("text")
        res = await reg.register(kind=kind, hash=f"sha256:{e.counter:064x}", title=name, location={"path": str(path)},
                                 size=1, modified=modified, captured=OCT, complete=True)
        return res["id"]

    e.workers, e.register = workers, register
    workers()
    yield e
    await http.aclose()
    await pool.close()


async def describe_all(e, rounds=30):
    for _ in range(rounds):
        n = await e.describer.step()
        await e.describer.wait_idle()
        if n == 0 and not e.describer.active:
            return


async def locate_all(e, rounds=30):
    for _ in range(rounds):
        if await e.locator.step() == 0:
            return


async def stage(e, sid, name="extract"):
    return (await e.reg.get_source(sid))["stages"][name]


async def doc(e, sid):
    return await e.reg.read_document(sid)


async def backlog_boundary_now(e):
    """Everything registered so far is the backlog: the service starts its first time now."""
    await asyncio.sleep(0.02)
    await e.describer.boundary()
    await asyncio.sleep(0.02)


# ---------------------------------------------------------------- flow and scope
async def test_new_jpeg_complete(env, gateway, geoapify_mock):  # AK-1, AK-21, AK-27
    await backlog_boundary_now(env)
    sid = await env.register(gps=RIMINI)
    await locate_all(env)
    await describe_all(env)
    d = await doc(env, sid)
    fm = d["frontmatter"]
    assert fm["taken"] == "2024-07-12T14:03:22" and (fm["width"], fm["height"]) == (60, 40)
    assert fm["gps"]["latitude"] == pytest.approx(44.0596, abs=1e-5)
    assert fm["camera"] == {"make": "Canon", "model": "EOS R5"}
    assert fm["location"] == {"country": "Italien", "country_code": "IT", "city": "Rimini", "district": "Marina Centro"}
    assert fm["description_model"] == "qwen3.8-27b" and fm["language"] == "de"
    assert fm["title"] == "2024-07-12 14.03.22 Strand bei Sonnenuntergang – Rimini"
    assert LONG_DESCRIPTION in d["content"] and "Text im Bild" not in d["content"]
    assert d["path"].endswith("-2024-07-12-14-03-22-strand-bei-sonnenuntergang-rimini.md")
    assert (await stage(env, sid))["state"] == "done" and (await stage(env, sid, "locate"))["state"] == "done"
    assert "Aufnahmeort laut GPS (Hinweis): Rimini, Italien." in gateway.requests[0]["prompt"]  # AK-19
    msgs = git(env.repo, "log", "--format=%an|%s").splitlines()
    assert any(m.startswith("Alice ETL|extract: " + sid) for m in msgs)
    assert any(m.startswith("Alice ETL|locate: " + sid) for m in msgs)


@pytest.mark.parametrize("ext", ["jpg", "jpeg", "png", "webp", "heic", "tif", "tiff"])
async def test_all_formats(env, ext):  # AK-2
    await backlog_boundary_now(env)
    sid = await env.register(f"bild.{ext}", gps=RIMINI)
    await describe_all(env)
    fm = (await doc(env, sid))["frontmatter"]
    assert (await stage(env, sid))["state"] == "done"
    assert fm["taken"] == "2024-07-12T14:03:22" and fm["camera"]["make"] == "Canon" and fm["gps"]


async def test_mail_attachment(env, nas):  # AK-3
    await backlog_boundary_now(env)
    mail = await env.reg.register(kind="email", hash="sha256:" + "e" * 64, title="Urlaub",
                                  location={"mailbox": "m1", "folder": "INBOX", "message_id": "<a@b>"},
                                  captured=OCT, complete=True)
    archive = nas / "mailarchiv"
    archive.mkdir()
    make_image(archive / "anhang.jpg", gps=RIMINI)
    sid = (await env.reg.register(kind="image", hash="sha256:" + "f" * 64, title="anhang.jpg",
                                  location={"path": str(archive / "anhang.jpg")}, parents=[mail["id"]],
                                  captured=OCT, complete=True))["id"]
    await locate_all(env)
    await describe_all(env)
    fm = (await doc(env, sid))["frontmatter"]
    assert fm["parents"] == [mail["id"]] and fm["title"].endswith("Strand bei Sonnenuntergang – Rimini")


async def test_other_kinds_untouched(env, gateway):  # AK-4, AK-5
    await backlog_boundary_now(env)
    doc_id = await env.register("brief.pdf", kind="document")
    before = (await doc(env, doc_id))
    img = await env.register()
    await locate_all(env)
    await describe_all(env)
    assert (await doc(env, doc_id)) == before
    assert (await stage(env, doc_id))["state"] == "pending" and (await stage(env, doc_id, "locate"))["state"] == "skipped"
    st = (await env.reg.get_source(img))["stages"]
    assert st["classify"]["state"] == "skipped" and st["database"]["state"] == "skipped"


async def test_deleted_image_not_handed_out(env, gateway):  # AK-6
    await backlog_boundary_now(env)
    sid = await env.register()
    await env.reg.remove_location(sid, {"path": str(env.nas / "IMG_1.jpg")})
    await describe_all(env)
    assert gateway.requests == [] and (await stage(env, sid))["state"] == "pending"


async def test_without_exif(env):  # AK-7
    await backlog_boundary_now(env)
    sid = await env.register("screenshot.png", size=(120, 80), exif=False)
    await locate_all(env)
    await describe_all(env)
    fm = (await doc(env, sid))["frontmatter"]
    assert fm["taken"] is None and fm["gps"] is None and fm["camera"] is None and fm["location"] is None
    assert (fm["width"], fm["height"]) == (120, 80)
    assert (await stage(env, sid))["state"] == "done" and (await stage(env, sid, "locate"))["state"] == "skipped"
    assert fm["title"] == "2026-10-14 09.32.11 Strand bei Sonnenuntergang"  # AK-28


async def test_exif_from_original_not_from_weaviate(env, weaviate_mock):  # AK-9
    await backlog_boundary_now(env)
    sid = await env.register(gps=RIMINI)
    weaviate_mock.objects[f"{env.counter:064x}"] = [{"country": "Italien", "country_code": "IT", "city": "Rimini",
                                                     "district": None, "camera_make": "Nikon",
                                                     "exif_datetime": "1999-01-01T00:00:00Z"}]
    await locate_all(env)
    await describe_all(env)
    fm = (await doc(env, sid))["frontmatter"]
    assert fm["camera"]["make"] == "Canon" and fm["taken"] == "2024-07-12T14:03:22"


# ---------------------------------------------------------------- place
async def test_takeover_without_geoapify(env, weaviate_mock, geoapify_mock):  # AK-10
    await backlog_boundary_now(env)
    sid = await env.register(gps=RIMINI)
    weaviate_mock.objects[f"{env.counter:064x}"] = [{"country": "Deutschland", "country_code": "de",
                                                     "city": "Köln", "district": "Ehrenfeld"}]
    await locate_all(env)
    assert (await doc(env, sid))["frontmatter"]["location"] == {"country": "Deutschland", "country_code": "DE",
                                                                 "city": "Köln", "district": "Ehrenfeld"}
    assert geoapify_mock.requests == []


async def test_weaviate_down_waits_then_takes_over(env, weaviate_mock, geoapify_mock):  # AK-12
    await backlog_boundary_now(env)
    sid = await env.register(gps=RIMINI)
    weaviate_mock.down = True
    await env.locator.step()
    st = await stage(env, sid, "locate")
    assert st["state"] == "pending" and st["attempts"] == 0 and geoapify_mock.requests == []
    assert any("Altes Weaviate nicht erreichbar" in w for w in env.locator.health()[1])
    # Weaviate is back: due again after the wait
    weaviate_mock.down = False
    weaviate_mock.objects[f"{env.counter:064x}"] = [{"country": "Italien", "country_code": "IT", "city": "Rimini",
                                                     "district": None}]
    env.locator.weaviate_paused_until = 0
    async with env.pool.acquire() as con:
        await con.execute("UPDATE alice.source_stages SET next_retry_at = NOW() WHERE stage = 'locate'")
    await locate_all(env)
    assert (await doc(env, sid))["frontmatter"]["location"]["city"] == "Rimini"
    assert geoapify_mock.requests == []


async def test_takeover_switched_off(env, weaviate_mock, geoapify_mock):  # AK-13
    env.workers(location_takeover=False)
    await backlog_boundary_now(env)
    sid = await env.register(gps=RIMINI)
    weaviate_mock.objects[f"{env.counter:064x}"] = [{"country": "X", "city": "Y"}]
    await locate_all(env)
    assert weaviate_mock.methods == [] and len(geoapify_mock.requests) == 1
    assert (await doc(env, sid))["frontmatter"]["location"]["city"] == "Rimini"


async def test_daily_limit_three_of_five(env, geoapify_mock):  # AK-14, EC-15
    day = [datetime(2026, 11, 27, 22, 0, tzinfo=ZoneInfo("Europe/Berlin"))]
    env.workers(geoapify_daily_limit=3)
    env.locator.clock = lambda: day[0]
    await backlog_boundary_now(env)
    ids = [await env.register(gps=RIMINI) for _ in range(5)]
    await locate_all(env)
    assert len(geoapify_mock.requests) == 3
    states = [await stage(env, s, "locate") for s in ids]
    assert sorted(s["state"] for s in states) == ["done"] * 3 + ["pending"] * 2
    waiting = [s for s in states if s["state"] == "pending"]
    assert all(s["attempts"] == 0 and s["next_retry_at"] is not None for s in waiting)
    # released until tomorrow (00:00 Berlin = 2 h later)
    assert all(timedelta(hours=1) < s["next_retry_at"] - datetime.now(timezone.utc) for s in waiting)
    assert await env.store.geocode_calls(date(2026, 11, 27)) == 3
    # next day: they run on their own
    day[0] = datetime(2026, 11, 28, 0, 5, tzinfo=ZoneInfo("Europe/Berlin"))
    async with env.pool.acquire() as con:
        await con.execute("UPDATE alice.source_stages SET next_retry_at = NOW() WHERE stage = 'locate' "
                          "AND state = 'pending'")
    await locate_all(env)
    assert len(geoapify_mock.requests) == 5
    assert [(await stage(env, s, "locate"))["state"] for s in ids] == ["done"] * 5


async def test_geoapify_error_leaves_description_alone(env, geoapify_mock, gateway):  # AK-16
    await backlog_boundary_now(env)
    sid = await env.register(gps=RIMINI)
    await describe_all(env)
    before = await doc(env, sid)
    geoapify_mock.status = 500
    await locate_all(env)
    st = await stage(env, sid, "locate")
    assert st["state"] == "failed" and st["attempts"] == 1 and st["next_retry_at"] is not None
    assert (await stage(env, sid))["state"] == "done" and len(gateway.requests) == 1
    after = await doc(env, sid)
    assert after["frontmatter"]["title"] == before["frontmatter"]["title"] and after["content"] == before["content"]


async def test_place_written_although_description_fails(env, gateway):  # AK-17
    await backlog_boundary_now(env)
    sid = await env.register(gps=RIMINI)
    gateway.down = True
    await describe_all(env)
    await locate_all(env)
    assert (await stage(env, sid))["state"] == "failed"
    fm = (await doc(env, sid))["frontmatter"]
    assert fm["location"]["city"] == "Rimini" and "description_model" not in fm
    assert fm["title"] == "IMG_1.jpg"  # not described yet: no place suffix on the file name title


# ---------------------------------------------------------------- description
async def test_text_in_image_section(env, gateway):  # AK-20
    await backlog_boundary_now(env)
    sid = await env.register()
    gateway.answers.append({"description": LONG_DESCRIPTION, "title": "Schild am Strand",
                            "text_in_image": "Bagno 42\n```Eis```"})
    await describe_all(env)
    assert "## Text im Bild\n\n````text\nBagno 42\n```Eis```\n````" in (await doc(env, sid))["content"]


async def test_panorama_end_to_end(env, gateway):  # AK-23
    await backlog_boundary_now(env)
    sid = await env.register("pano.jpg", size=(22704, 1760), exif=False)
    await describe_all(env)
    assert len(gateway.requests) == 9 and all(max(s) <= 1024 for r in gateway.requests for s in r["sizes"])
    d = await doc(env, sid)
    assert d["content"].count(LONG_DESCRIPTION) == 1 and d["frontmatter"]["description_model"]


async def test_panorama_tile_fails_nothing_written(env, gateway):  # AK-24
    await backlog_boundary_now(env)
    sid = await env.register("pano.jpg", size=(22704, 1760), exif=False)
    before = await doc(env, sid)
    gateway.answers.extend([gateway.tile_default, gateway.tile_default, "kein json"])
    await env.describer.step()
    await env.describer.wait_idle()
    st = await stage(env, sid)
    assert st["state"] == "failed" and st["attempts"] == 1 and st["next_retry_at"] is not None
    assert await doc(env, sid) == before


async def test_too_large_and_broken_fail_permanently(env, gateway, nas):  # AK-25
    from .test_imaging import _png_header

    await backlog_boundary_now(env)
    (nas / "riesig.png").write_bytes(_png_header(20000, 13000))
    (nas / "kaputt.jpg").write_bytes(b"\xff\xd8\xff garbage")
    big = await env.register("riesig.png")
    broken = await env.register("kaputt.jpg")
    await describe_all(env)
    assert gateway.requests == []
    for sid, reason in ((big, "Bild zu groß"), (broken, "nicht lesbar")):
        st = await stage(env, sid)
        assert st["state"] == "failed_permanent" and reason in st["last_error"]


@pytest.mark.parametrize("fault", ["down", "empty", "timeout"])
async def test_vision_errors_retry_by_backoff(env, gateway, fault):  # AK-26
    await backlog_boundary_now(env)
    sid = await env.register()
    before = await doc(env, sid)
    if fault == "down":
        gateway.down = True
    elif fault == "empty":
        gateway.answers.append("")
    else:
        gateway.answers.append(httpx.ReadTimeout("slow"))
    await env.describer.step()
    await env.describer.wait_idle()
    st = await stage(env, sid)
    assert st["state"] == "failed" and st["attempts"] == 1 and st["next_retry_at"] is not None
    assert await doc(env, sid) == before


# ---------------------------------------------------------------- title
async def test_place_after_description_completes_title(env, geoapify_mock):  # AK-29
    await backlog_boundary_now(env)
    sid = await env.register(gps=RIMINI)
    await describe_all(env)
    assert (await doc(env, sid))["frontmatter"]["title"] == "2024-07-12 14.03.22 Strand bei Sonnenuntergang"
    await locate_all(env)
    d = await doc(env, sid)
    assert d["frontmatter"]["title"] == "2024-07-12 14.03.22 Strand bei Sonnenuntergang – Rimini"
    assert "rimini" in d["path"]


async def test_manual_title_and_content_protected(env, gateway):  # AK-30, AK-35
    await backlog_boundary_now(env)
    sid = await env.register(gps=RIMINI)
    await describe_all(env)
    path = env.repo / (await doc(env, sid))["path"]
    text = path.read_text().replace("title: 2024-07-12 14.03.22 Strand bei Sonnenuntergang",
                                    "title: Mein Lieblingsstrand")
    text = text.replace(LONG_DESCRIPTION, "Von Hand beschrieben.")
    path.write_text(text)
    await env.reg.scan()
    # description runs again (rebuild-like retry) and the place arrives
    await env.reg.retry(sid, "extract")
    gateway.default = {"description": LONG_DESCRIPTION + " Neu.", "title": "Anderer Titel", "text_in_image": ""}
    await describe_all(env)
    await locate_all(env)
    d = await doc(env, sid)
    assert d["frontmatter"]["title"] == "Mein Lieblingsstrand"
    assert "title" in d["frontmatter"]["manual"] and "content" in d["frontmatter"]["manual"]
    assert "Von Hand beschrieben." in d["content"] and "Neu." not in d["content"]
    assert d["frontmatter"]["location"]["city"] == "Rimini" and d["frontmatter"]["description_model"]


# ---------------------------------------------------------------- order, backlog, trigger
async def test_backlog_locked_only_new_described_place_for_both(env, gateway):  # AK-31
    old = await env.register(gps=RIMINI)
    await backlog_boundary_now(env)
    new = await env.register(gps=RIMINI)
    await describe_all(env)
    await locate_all(env)
    assert (await stage(env, new))["state"] == "done" and (await stage(env, old))["state"] == "pending"
    assert len(gateway.requests) == 1
    assert (await stage(env, old, "locate"))["state"] == "done" and (await stage(env, new, "locate"))["state"] == "done"


async def test_new_before_backlog_when_released(env, gateway):  # AK-32
    env.workers(backlog_released=True)
    backlog = [await env.register() for _ in range(3)]
    await backlog_boundary_now(env)
    await env.describer.step()  # one backlog image (no new one yet)
    await env.describer.wait_idle()
    new = await env.register()
    await env.describer.step()
    await env.describer.wait_idle()
    assert (await stage(env, new))["state"] == "done"
    assert sorted([(await stage(env, b))["state"] for b in backlog]) == ["done", "pending", "pending"]
    await describe_all(env)
    assert [(await stage(env, b))["state"] for b in backlog] == ["done"] * 3


async def test_trigger_one_backlog_image(env, gateway):  # AK-33
    from app import main

    a, b = await env.register(), await env.register()
    await backlog_boundary_now(env)
    main.app.state.registry, main.app.state.store = env.client, env.store
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://img") as c:
        r = await c.post(f"/describe/{b}")
        assert r.status_code == 200, r.text
        assert (await c.post("/describe/zzzzzzzzzzzz")).status_code == 404
        doc_id = await env.register("brief.pdf", kind="document")
        assert (await c.post(f"/describe/{doc_id}")).status_code == 409
        assert (await c.post("/describe/..%2Fetc")).status_code in (400, 404)
    await describe_all(env)
    assert (await stage(env, b))["state"] == "done" and (await stage(env, a))["state"] == "pending"
    assert len(gateway.requests) == 1 and await env.store.requested() == []
    # a described image can be triggered again (sample after a prompt change)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://img") as c:
        assert (await c.post(f"/describe/{b}")).status_code == 200
    await describe_all(env)
    assert len(gateway.requests) == 2


async def test_concurrency_one(env, gateway):  # AK-34
    gateway.delay = 0.05
    await backlog_boundary_now(env)
    ids = [await env.register() for _ in range(4)]
    for _ in range(20):
        await env.describer.step()
    await env.describer.wait_idle()
    await describe_all(env)
    assert gateway.max_active == 1 and len(gateway.requests) == 4
    assert [(await stage(env, s))["state"] for s in ids] == ["done"] * 4


async def test_changed_original_runs_again(env, gateway, geoapify_mock, nas):  # AK-36
    await backlog_boundary_now(env)
    sid = await env.register("wechsel.jpg", exif=False)
    await locate_all(env)
    await describe_all(env)
    assert (await stage(env, sid, "locate"))["state"] == "skipped"
    make_image(nas / "wechsel.jpg", gps=RIMINI, taken="2025:01:02 03:04:05")  # new content, now with GPS
    await env.reg.update_original(sid, hash="sha256:" + "9" * 64, size=2, modified=OCT)
    await locate_all(env)
    await describe_all(env)
    fm = (await doc(env, sid))["frontmatter"]
    assert fm["taken"] == "2025-01-02T03:04:05" and fm["location"]["city"] == "Rimini"
    assert fm["title"] == "2025-01-02 03.04.05 Strand bei Sonnenuntergang – Rimini"
    assert len(gateway.requests) == 2 and len(geoapify_mock.requests) == 1


async def test_nas_down_releases_without_attempt(env, gateway, nas):  # AK-38
    await backlog_boundary_now(env)
    sid = await env.register()
    for f in nas.iterdir():
        f.unlink()  # empty mount point = share missing
    await env.describer.step()
    await env.describer.wait_idle()
    st = await stage(env, sid)
    assert st["state"] == "pending" and st["attempts"] == 0 and gateway.requests == []
