"""
Shared fixtures.

Integration tests need a PostgreSQL with sql/init-schema.sql applied; they are
skipped unless TEST_POSTGRES_DSN is set (scripts/test-services.sh does that).

The watched "NAS" is a temporary folder. The register is the real
alice-source-registry (loaded in-process under the package name registry_app,
called over HTTP through an ASGI transport) with a temporary git repo, so the
tests cover both services end to end.
"""
import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.detector import Detector
from app.registry import RegistryClient

DSN = os.environ.get("TEST_POSTGRES_DSN")
REGISTRY_DIR = Path(__file__).resolve().parents[2] / "alice-source-registry"
DEFAULT_STAGES = ("detect", "extract", "classify", "database", "rag", "wiki", "thumbnail")


def _load_registry():
    if "registry_app" not in sys.modules:
        spec = importlib.util.spec_from_file_location("registry_app", REGISTRY_DIR / "app" / "__init__.py",
                                                      submodule_search_locations=[str(REGISTRY_DIR / "app")])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["registry_app"] = mod
        spec.loader.exec_module(mod)
    return (importlib.import_module("registry_app.main"), importlib.import_module("registry_app.service"),
            importlib.import_module("registry_app.config"))


def git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "safe.directory=*", *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
async def pool():
    if not DSN:
        pytest.skip("TEST_POSTGRES_DSN not set")
    import asyncpg

    p = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=10)
    async with p.acquire() as con:
        await con.execute("TRUNCATE alice.sources CASCADE")
        await con.execute("DELETE FROM alice.pipeline_stages WHERE NOT (name = ANY($1::text[]))", list(DEFAULT_STAGES))
        await con.execute("TRUNCATE alice.detect_files, alice.detect_dirs, alice.detect_pending, "
                          "alice.detect_problems, alice.detect_runs, alice.dms_watched_folders, alice.detect_hash_cycle")
    yield p
    await p.close()


@pytest.fixture
def nas(tmp_path):
    d = tmp_path / "nas"
    d.mkdir()
    return d


@pytest.fixture
def repo_dir(tmp_path):
    d = tmp_path / "sot"
    d.mkdir()
    return d


@pytest.fixture
async def registry_service(pool, repo_dir):
    main, service, config = _load_registry()
    reg = service.Registry(config.Settings(repo_path=str(repo_dir), postgres_dsn=DSN), pool, None)
    await reg.startup()
    main.app.state.reg = reg
    return reg


@pytest.fixture
async def registry(registry_service):
    main, _, _ = _load_registry()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://registry")
    rc = RegistryClient("http://registry", client=client)
    yield rc
    await client.aclose()


@pytest.fixture
def make_detector(pool, nas):
    def make(registry, **overrides) -> Detector:
        settings = Settings(postgres_dsn=DSN, nas_root=str(nas), **overrides)
        return Detector(settings, pool, registry)
    return make


@pytest.fixture
def det(make_detector, registry):
    return make_detector(registry)


@pytest.fixture
def add_folder(pool):
    async def add(path, enabled=True):
        path = str(path)
        os.makedirs(path, exist_ok=True)
        async with pool.acquire() as con:
            await con.execute("INSERT INTO alice.dms_watched_folders (path, enabled) VALUES ($1, $2)", path, enabled)
        return path
    return add


async def run(det, kind="day"):
    return await det.start(kind)
