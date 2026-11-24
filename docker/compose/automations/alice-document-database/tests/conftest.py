"""
Shared fixtures.

End-to-end environment: the real register code (alice-source-registry, loaded in-process) with the
throwaway PostgreSQL (TEST_POSTGRES_DSN, set by scripts/test-services.sh) and a temporary git repo;
the database worker talks to the register over its HTTP interface (ASGI transport) and writes the
tables alice.doc_* of the same test database. Skipped without TEST_POSTGRES_DSN. No LLM: the
classification result is written through the register like alice-document-classify does.

Test IBANs/ISINs are synthetic, built here with valid check digits.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import Settings
from app.registry import RegistryClient
from app.store import Store
from app.worker import Worker

DSN = os.environ.get("TEST_POSTGRES_DSN")
REGISTRY_DIR = pathlib.Path(__file__).resolve().parents[2] / "alice-source-registry" / "app"
NOV = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)


def make_iban(account: str, bank: str = "10020030", country: str = "DE") -> str:
    """Synthetic IBAN with valid check digits (mod 97)."""
    bban = bank + account.zfill(10)
    digits = "".join(str(int(c, 36)) for c in bban + country + "00")
    return f"{country}{98 - int(digits) % 97:02d}{bban}"


def make_isin(body: str = "XS000000001") -> str:
    """Synthetic ISIN with valid Luhn check digit."""
    digits = "".join(str(int(c, 36)) for c in body)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return body + str((10 - total % 10) % 10)


IBAN_A = make_iban("1234567")
IBAN_B = make_iban("7654321")
ISIN = make_isin()


def load_registry():
    if "registry_app" not in sys.modules:
        spec = importlib.util.spec_from_file_location("registry_app", REGISTRY_DIR / "__init__.py",
                                                      submodule_search_locations=[str(REGISTRY_DIR)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["registry_app"] = mod
        spec.loader.exec_module(mod)
    import registry_app.config as rconfig
    import registry_app.main as rmain
    import registry_app.markdown as rmd
    import registry_app.service as rservice
    return rmain, rconfig, rservice, rmd


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "safe.directory=*", *args], capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture
def settings():
    return Settings(registry_url="http://registry", postgres_dsn=DSN or "", concurrency=2, poll_seconds=0.01,
                    heartbeat_seconds=30, db_retry_seconds=0.05)


class Env:
    async def register(self, title="scan.pdf", captured=NOV, path=None, kind="document"):
        self.counter += 1
        res = await self.reg.register(kind=kind, hash=f"sha256:{self.counter:016d}", title=title,
                                      location={"path": path or f"/mnt/nas/share/{self.counter}-{title}"},
                                      size=1, modified=captured, captured=captured, complete=True)
        return res["id"]

    async def _claim(self, stage, sid, kinds=("document",)):
        items = (await self.reg.claim(stage, 100, list(kinds)))["items"]
        token = None
        for it in items:
            if it["source_id"] == sid:
                token = it["token"]
            else:
                await self.reg.release(it["source_id"], stage, it["token"])
        assert token, f"{stage} of {sid} not claimable"
        return token

    async def extract(self, sid, content="## Seite 1\n\nText\n", kind="document"):
        tok = await self._claim("extract", sid, (kind,))
        await self.reg.write_document(sid, stage="extract", content=content, fields={"language": "de"})
        await self.reg.complete(sid, "extract", tok)

    async def classify(self, sid, doc_type, fields, *, title="Testdokument", summary="Eine Zusammenfassung.",
                       confidence=0.9, uncertain=False, lang_uncertain=False, kind="document"):
        """What alice-document-classify writes (PROJ-118), without an LLM."""
        tok = await self._claim("classify", sid, (kind,))
        res = await self.reg.write_document(sid, stage="classify", token=tok, fields={
            "type": doc_type, "title": title, "summary": summary,
            "classification": {"confidence": confidence, "uncertain": uncertain},
            "summary_language_uncertain": lang_uncertain, "fields": fields})
        assert not res.get("discarded")
        await self.reg.complete(sid, "classify", tok)

    async def add(self, doc_type, fields, captured=NOV, **kw):
        sid = await self.register(captured=captured)
        await self.extract(sid)
        await self.classify(sid, doc_type, fields, **kw)
        return sid

    async def run(self):
        for _ in range(200):
            n = await self.worker.step()
            await self.worker.wait_idle()
            if n == 0 and not self.worker.active:
                return

    async def stage(self, sid, name="database"):
        return (await self.reg.get_source(sid))["stages"][name]

    async def frontmatter(self, sid):
        return (await self.reg.read_document(sid))["frontmatter"]

    async def hand_edit(self, sid, mutate):
        """A human edits the source markdown (uncommitted) and the register's scan takes it over."""
        path = self.repo / (await self.reg.get_source(sid))["path"]
        fm, content = self.md.parse(path.read_text())
        mutate(fm)
        path.write_text(self.md.render(fm, content))
        await self.reg.scan()

    async def hand_edit_text(self, sid, old, new):
        path = self.repo / (await self.reg.get_source(sid))["path"]
        text = path.read_text()
        assert old in text, old
        path.write_text(text.replace(old, new, 1))
        await self.reg.scan()

    async def delete(self, sid):
        src = await self.reg.get_source(sid)
        for loc in src["locations"]:
            if loc["present"]:
                await self.reg.remove_location(sid, {"path": loc["path"]})

    async def fetch(self, sql, *args):
        async with self.pool.acquire() as con:
            return await con.fetch(sql, *args)

    async def fetchrow(self, sql, *args):
        async with self.pool.acquire() as con:
            return await con.fetchrow(sql, *args)

    async def fetchval(self, sql, *args):
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, *args)


@pytest.fixture
async def env(tmp_path, settings):
    if not DSN:
        pytest.skip("TEST_POSTGRES_DSN not set")
    import asyncpg

    rmain, rconfig, rservice, rmd = load_registry()
    pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=10)
    async with pool.acquire() as con:
        await con.execute("TRUNCATE alice.sources CASCADE")
        await con.execute("TRUNCATE alice.doc_documents CASCADE")
    repo = tmp_path / "sot"
    repo.mkdir()
    reg = rservice.Registry(rconfig.Settings(repo_path=str(repo), postgres_dsn=DSN), pool, None)
    await reg.startup()
    rmain.app.state.reg = reg
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=rmain.app), base_url="http://registry")
    e = Env()
    e.reg, e.repo, e.pool, e.md, e.counter = reg, repo, pool, rmd, 0
    e.client = RegistryClient("http://registry", client=http)
    e.store = Store(DSN)
    e.worker = Worker(settings, e.client, e.store)
    yield e
    await e.worker.stop()
    await e.store.close()
    await http.aclose()
    await pool.close()


def later(minutes: int) -> datetime:
    return NOV + timedelta(minutes=minutes)
