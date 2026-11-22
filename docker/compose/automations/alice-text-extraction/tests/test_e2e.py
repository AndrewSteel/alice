"""End to end: the real register code (alice-source-registry, loaded in-process) with a throwaway
PostgreSQL and a temporary git repo, the extraction worker talking to it over its HTTP interface.
Skipped without TEST_POSTGRES_DSN (scripts/test-services.sh sets it)."""
import importlib.util
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

import httpx
import pytest

from app.registry import RegistryClient
from app.worker import Worker

from .conftest import make_pdf, write
from .test_formats import DE, EN

DSN = os.environ.get("TEST_POSTGRES_DSN")
REGISTRY_DIR = pathlib.Path(__file__).resolve().parents[2] / "alice-source-registry" / "app"
NOV = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)


def _load_registry():
    if "registry_app" not in sys.modules:
        spec = importlib.util.spec_from_file_location("registry_app", REGISTRY_DIR / "__init__.py",
                                                      submodule_search_locations=[str(REGISTRY_DIR)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["registry_app"] = mod
        spec.loader.exec_module(mod)
    import registry_app.main as rmain
    import registry_app.config as rconfig
    import registry_app.service as rservice
    return rmain, rconfig, rservice


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "safe.directory=*", *args], capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture
async def env(tmp_path, settings):
    if not DSN:
        pytest.skip("TEST_POSTGRES_DSN not set")
    import asyncpg

    rmain, rconfig, rservice = _load_registry()
    pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=10)
    async with pool.acquire() as con:
        await con.execute("TRUNCATE alice.sources CASCADE")
    repo = tmp_path / "sot"
    repo.mkdir()
    reg = rservice.Registry(rconfig.Settings(repo_path=str(repo), postgres_dsn=DSN), pool, None)
    await reg.startup()
    rmain.app.state.reg = reg
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=rmain.app), base_url="http://registry")
    client = RegistryClient("http://registry", client=http)

    class Env:
        pass

    e = Env()
    e.reg, e.repo, e.pool, e.client = reg, repo, pool, client
    e.make_worker = lambda ext: Worker(settings, client, ext)

    async def register(path, title, kind="document", h=None):
        res = await reg.register(kind=kind, hash=h or "sha256:" + format(abs(hash(path)), "x").rjust(16, "0"),
                                 title=title, location={"path": str(path)}, size=1, modified=NOV, captured=NOV,
                                 complete=True)
        return res["id"]

    e.register = register
    yield e
    await http.aclose()
    await pool.close()


async def run(e, w):
    for _ in range(50):
        n = await w.step()
        await w.wait_idle()
        if n == 0 and not w.active:
            return


async def stage(e, sid, name="extract"):
    return (await e.reg.get_source(sid))["stages"][name]


async def doc(e, sid):
    return await e.reg.read_document(sid)


async def test_extract_writes_and_commits(env, settings, extractor, nas):  # AK-1, AK-2, AK-5, AK-17, AK-18
    path = make_pdf(nas / "share" / "brief.pdf", [DE, EN])
    sid = await env.register(path, "brief.pdf")
    img = await env.register(write(nas / "share" / "foto.jpg", b"\xff\xd8jpeg"), "foto.jpg", kind="image")
    before_img = (env.repo / (await env.reg.get_source(img))["path"]).read_text()
    w = env.make_worker(extractor)
    await run(env, w)
    assert (await stage(env, sid))["state"] == "done"
    d = await doc(env, sid)
    fm = d["frontmatter"]
    assert fm["extraction"] == {"method": "text", "ocr_pages": [], "empty": False}
    assert fm["language"] == "de"
    assert "## Seite 1" in d["content"] and "## Seite 2" in d["content"]
    for key in fm:  # AK-17: no state, error or retry counter in the frontmatter
        assert key not in ("state", "attempts", "error", "last_error", "retries")
    log = git(env.repo, "log", "--format=%an|%s").splitlines()
    assert log[0] == f"Alice ETL|extract: {sid} brief.pdf"
    assert sum(1 for line in log if line.startswith("Alice ETL|extract:")) == 1
    # AK-3: the image is neither claimed nor changed
    assert (await stage(env, img))["state"] == "pending"
    assert (env.repo / (await env.reg.get_source(img))["path"]).read_text() == before_img


async def test_batch_commit(env, settings, extractor, nas):  # AK-2 (mass run)
    settings.batch = True
    ids = [await env.register(write(nas / "share" / f"n{i}.txt", f"Notiz {i}"), f"n{i}.txt") for i in range(3)]
    await run(env, env.make_worker(extractor))
    await env.reg.flush_due(force=True)
    log = git(env.repo, "log", "--format=%s").splitlines()
    assert log[0] == "rebuild: extract 3 sources"
    assert not [line for line in log if line.startswith("extract:")]
    for i in ids:
        assert (await stage(env, i))["state"] == "done"


async def test_permanent_and_retry(env, settings, extractor, nas):  # AK-21, AK-22, AK-27
    path = make_pdf(nas / "share" / "geheim.pdf", [DE], password="pw")
    sid = await env.register(path, "geheim.pdf")
    before = (await doc(env, sid))["content"]
    await run(env, env.make_worker(extractor))
    st = await stage(env, sid)
    assert st["state"] == "failed_permanent" and st["attempts"] == 1
    assert st["last_error"] == "PDF ist passwortgeschützt"
    assert (await doc(env, sid))["content"] == before
    # "erneut versuchen" after the human removed the password
    make_pdf(path, [DE])
    await env.reg.retry(sid, "extract")
    await run(env, env.make_worker(extractor))
    assert (await stage(env, sid))["state"] == "done"


async def test_manual_protection_and_hand_edit(env, settings, extractor, nas):  # AK-19, AK-28, AK-29
    path = write(nas / "share" / "notiz.txt", "Erster Stand " + DE)
    sid = await env.register(path, "notiz.txt")
    await run(env, env.make_worker(extractor))
    rel = (await env.reg.get_source(sid))["path"]
    md_file = env.repo / rel
    # human edits content and language without committing (AK-29), then the stage runs again
    text = md_file.read_text().replace("language: de", "language: fr").replace("Erster Stand", "Von Hand korrigiert")
    md_file.write_text(text)
    write(path, "Neuer Stand " + EN)
    await env.reg.retry(sid, "extract")
    await run(env, env.make_worker(extractor))
    log = git(env.repo, "log", "--format=%an|%s").splitlines()
    # the hand edit is committed first; the extraction then has nothing left to change
    # (content and language are protected, extraction is the same) → no further commit
    assert log[0].startswith("Alice Hand-Korrektur|manual:") and log[1].startswith("Alice ETL|extract:")
    d = await doc(env, sid)
    assert "Von Hand korrigiert" in d["content"] and "Neuer Stand" not in d["content"]  # AK-28
    assert d["frontmatter"]["language"] == "fr"  # AK-19
    assert set(d["frontmatter"]["manual"]) >= {"content", "language"}
    assert d["frontmatter"]["extraction"]["method"] == "text"


async def test_changed_text_resets_and_same_text_no_commit(env, settings, extractor, nas):  # AK-30, AK-31
    path = write(nas / "share" / "vertrag.txt", "Version eins " + DE)
    sid = await env.register(path, "vertrag.txt")
    await run(env, env.make_worker(extractor))
    for name in ("classify", "database", "rag", "wiki"):
        items = (await env.reg.claim(name, 10))["items"]
        for it in items:
            await env.reg.complete(it["source_id"], name, it["token"])
    # unchanged text: no commit, nothing reset (AK-31)
    head = git(env.repo, "rev-parse", "HEAD")
    await env.reg.retry(sid, "extract")
    await run(env, env.make_worker(extractor))
    assert git(env.repo, "rev-parse", "HEAD") == head
    for n in ("database", "rag", "wiki"):
        assert (await stage(env, sid, n))["state"] == "done", n
    # original changed in place (PROJ-116 resets the stages after detect), new text (AK-30)
    write(path, "Version zwei " + DE)
    await env.reg.update_original(sid, hash="sha256:" + "9" * 16, size=2, modified=NOV)
    await run(env, env.make_worker(extractor))
    d = await doc(env, sid)
    assert d["id"] == sid and "Version zwei" in d["content"]
    for n in ("database", "rag", "wiki"):
        assert (await stage(env, sid, n))["state"] == "pending", n
    rel = (await env.reg.get_source(sid))["path"]
    assert "Version eins" in git(env.repo, "show", f"HEAD~1:{rel}")


async def test_empty_and_special_characters(env, settings, extractor, nas):  # AK-20, EC-7
    empty = await env.register(make_pdf(nas / "share" / "leer.pdf", [None]), "leer.pdf")
    tricky = await env.register(write(nas / "share" / "t.md", "---\nid: fake\n---\n# Titel\n```\ncode\n```\n"),
                                "t.md")
    await run(env, env.make_worker(extractor))
    d = await doc(env, empty)
    assert d["frontmatter"]["extraction"]["empty"] is True and d["content"].startswith("Kein Text extrahiert")
    assert (await stage(env, empty))["state"] == "done"
    assert (await stage(env, empty, "classify"))["state"] == "pending"  # following stages not blocked
    t = await doc(env, tricky)
    assert t["frontmatter"]["id"] == tricky and "id: fake" in t["content"] and "```\ncode\n```" in t["content"]


async def test_two_workers_process_once(env, settings, extractor, nas):  # AK-4
    sid = await env.register(write(nas / "share" / "x.txt", "Hallo " + DE), "x.txt")
    a, b = env.make_worker(extractor), env.make_worker(extractor)
    import asyncio

    await asyncio.gather(a.step(), b.step())
    await asyncio.gather(a.wait_idle(), b.wait_idle())
    assert a.stats["done"] + b.stats["done"] == 1
    log = git(env.repo, "log", "--format=%s").splitlines()
    assert sum(1 for line in log if line.startswith(f"extract: {sid}")) == 1
