"""
Shared fixtures.

End-to-end environment: the real register (alice-source-registry) and the real detection
(alice-file-detection), both loaded in-process and called over HTTP (ASGI transport), with the
throwaway PostgreSQL (TEST_POSTGRES_DSN, set by scripts/test-services.sh), a temporary git repo
and temporary folders as NAS. The stage services are simulated by small workers that claim and
complete work through the register like extract/classify/database do (no LLM). Skipped without
TEST_POSTGRES_DSN.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone

import httpx
import pytest

from app.clients import DetectionClient, RegistryClient
from app.config import Settings
from app.rebuild import Rebuilds
from app.reconcile import Reconciler

DSN = os.environ.get("TEST_POSTGRES_DSN")
AUTOMATIONS = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_STAGES = ("detect", "extract", "classify", "database", "rag", "wiki", "thumbnail")
NOV = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
REQUIRES = {"extract": None, "classify": ["extract"], "database": ["classify"]}


def _load(name: str, folder: str):
    if name not in sys.modules:
        d = AUTOMATIONS / folder / "app"
        spec = importlib.util.spec_from_file_location(name, d / "__init__.py", submodule_search_locations=[str(d)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return name


def registry_modules():
    n = _load("registry_app", "alice-source-registry")
    return (importlib.import_module(f"{n}.main"), importlib.import_module(f"{n}.service"),
            importlib.import_module(f"{n}.config"), importlib.import_module(f"{n}.markdown"))


def detection_modules():
    n = _load("detection_app", "alice-file-detection")
    return (importlib.import_module(f"{n}.main"), importlib.import_module(f"{n}.detector"),
            importlib.import_module(f"{n}.config"), importlib.import_module(f"{n}.registry"))


def git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "safe.directory=*", *args], capture_output=True,
                          text=True, check=True).stdout


class Env:
    counter = 0

    # ------------------------------------------------------------ sources
    async def add(self, n=1, kind="document", done=("extract", "classify", "database"), title="doc"):
        """n sources with the given stages done (like after a normal run)."""
        ids = []
        for _ in range(n):
            Env.counter += 1
            c = Env.counter
            r = await self.reg.register(kind=kind, hash=f"sha256:{c:020d}", title=f"{title}{c}.pdf",
                                        location={"path": f"/nas/share/{title}{c}.pdf"}, size=10, modified=NOV,
                                        captured=NOV, complete=True)
            ids.append(r["id"])
        if done and kind == "document":
            for stage in done:
                await self.work(stage, only=set(ids))
        return ids

    # ------------------------------------------------------------ simulated stage services
    async def work(self, stage, *, limit=1000, only=None, fail=None, kinds=("document",)):
        """Claim due work of `stage` and complete it like the stage service would. `fail`: ids → error."""
        res = await self.reg.claim(stage, min(limit, 100), list(kinds), REQUIRES.get(stage),
                                   stage == "database")
        items = res["items"]
        n = 0
        for it in items:
            sid, tok = it["source_id"], it["token"]
            if only is not None and sid not in only:
                await self.reg.release(sid, stage, tok)
                continue
            if fail and sid in fail:
                await self.reg.fail(sid, stage, tok, f"Fehler in {stage}", permanent=fail[sid])
                n += 1
                continue
            self.claimed.setdefault(stage, []).append(sid)
            if stage == "extract":
                await self.reg.write_document(sid, stage="extract", token=tok,
                                              content=f"## Seite 1\n\nText {self.version}\n", fields={"language": "de"})
            elif stage == "classify":
                await self.reg.write_document(sid, stage="classify", token=tok, fields={
                    "type": "Document", "summary": f"Zusammenfassung {self.version}"})
            elif stage == "database":
                async with self.pool.acquire() as con:
                    if it["deleted"]:
                        await con.execute("DELETE FROM alice.doc_documents WHERE id = $1", sid)
                    else:
                        fm = (await self.reg.read_document(sid))["frontmatter"]
                        await con.execute("DELETE FROM alice.doc_documents WHERE id = $1", sid)
                        await con.execute("INSERT INTO alice.doc_documents (id, type, title, summary, markdown_path) "
                                          "VALUES ($1, 'Document', $2, $3, $4)", sid, fm["title"], fm.get("summary"),
                                          it["path"])
            await self.reg.complete(sid, stage, tok)
            n += 1
        if len(items) == min(limit, 100) and n:
            n += await self.work(stage, limit=limit - len(items), only=only, fail=fail, kinds=kinds)
        return n

    async def work_all(self, **kw):
        n = 0
        for stage in ("extract", "classify", "database"):
            n += await self.work(stage, **kw)
        return n

    async def drive(self, run_id, rounds=200, check=None, **kw):
        """Tick the rebuild and let the stage services work until the run is over."""
        for _ in range(rounds):
            self.reg.last_tick = time.monotonic()  # no background monitor of the register in tests
            await self.rebuilds.tick()
            if check:
                await check()
            p = await self.rebuilds.progress(run_id)
            if p["status"] in ("done", "cancelled") and p.get("finished_at"):
                return p
            await self.work_all(**kw)
        raise AssertionError(f"run {run_id} did not finish: {await self.rebuilds.progress(run_id)}")

    async def stage(self, sid, name):
        return (await self.reg.get_source(sid))["stages"][name]

    async def fetch(self, sql, *args):
        async with self.pool.acquire() as con:
            return await con.fetch(sql, *args)

    async def fetchval(self, sql, *args):
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, *args)

    async def execute(self, sql, *args):
        async with self.pool.acquire() as con:
            return await con.execute(sql, *args)


@pytest.fixture
def settings():
    return Settings(postgres_dsn=DSN or "", registry_url="http://registry", detection_url="http://detection",
                    stage_limit=1000, tick_seconds=0.01)


@pytest.fixture
async def env(tmp_path, settings):
    if not DSN:
        pytest.skip("TEST_POSTGRES_DSN not set")
    import asyncpg

    rmain, rservice, rconfig, rmd = registry_modules()
    dmain, ddetector, dconfig, dregistry = detection_modules()
    pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=20)
    async with pool.acquire() as con:
        await con.execute("TRUNCATE alice.sources, alice.rebuild_runs, alice.reconcile_results, alice.doc_documents, "
                          "alice.detect_files, alice.detect_dirs, alice.detect_pending, alice.detect_problems, "
                          "alice.detect_runs, alice.detect_hash_cycle, alice.dms_watched_folders, "
                          "alice.pipeline_stage_served CASCADE")
        await con.execute("DELETE FROM alice.pipeline_stages WHERE NOT (name = ANY($1::text[]))", list(DEFAULT_STAGES))
        # what is served in production today (option A of #12)
        await con.execute("INSERT INTO alice.pipeline_stage_served (stage, kind) SELECT 'detect', k "
                          "FROM unnest(ARRAY['document','image','email','audio','video']) k")
        await con.execute("INSERT INTO alice.pipeline_stage_served (stage, kind) VALUES "
                          "('extract','document'), ('classify','document'), ('database','document')")
    repo = tmp_path / "sot"
    repo.mkdir()
    nas = tmp_path / "nas"
    nas.mkdir()
    reg = rservice.Registry(rconfig.Settings(repo_path=str(repo), postgres_dsn=DSN), pool, None)
    await reg.startup()
    rmain.app.state.reg = reg
    rhttp = httpx.AsyncClient(transport=httpx.ASGITransport(app=rmain.app), base_url="http://registry")
    det = ddetector.Detector(dconfig.Settings(postgres_dsn=DSN, nas_root=str(nas)), pool,
                             dregistry.RegistryClient("http://registry", client=rhttp))
    dmain.app.state.det = det
    dhttp = httpx.AsyncClient(transport=httpx.ASGITransport(app=dmain.app), base_url="http://detection")

    e = Env()
    e.reg, e.det, e.pool, e.repo, e.nas, e.md, e.version = reg, det, pool, repo, nas, rmd, 1
    e.claimed = {}
    e.settings = settings
    e.registry_http, e.detection_http = rhttp, dhttp
    e.registry = RegistryClient("http://registry", 30, client=rhttp)
    e.detection = DetectionClient("http://detection", 30, client=dhttp)
    e.rebuilds = Rebuilds(settings, pool, e.registry)
    e.reconciler = Reconciler(settings, pool, e.registry, e.detection)
    yield e
    if e.reconciler.task and not e.reconciler.task.done():
        e.reconciler.task.cancel()
    await rhttp.aclose()
    await dhttp.aclose()
    await pool.close()
