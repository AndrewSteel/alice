"""
Shared fixtures.

- The service app is called in-process over HTTP (ASGI transport) with the throwaway PostgreSQL
  (TEST_POSTGRES_DSN, set by scripts/test-services.sh); DB tests are skipped without it.
- The real register (alice-source-registry) runs in-process too (temporary git repo, no Redis),
  so "retry" goes through its real route.
- PROJ-120 (alice-etl-rebuild) is a small fake with fixed data (AK-23: "PROJ-120 im Test mit festen
  Fortschrittsdaten") that records every call.
- JWTs are signed with a throwaway RSA key pair generated per test session.
"""
from __future__ import annotations

import importlib
import json
import importlib.util
import os
import pathlib
import sys
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import main
from app.config import Settings
from app.upstream import Client

DSN = os.environ.get("TEST_POSTGRES_DSN")
AUTOMATIONS = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_STAGES = ("detect", "extract", "locate", "classify", "database", "rag", "wiki", "thumbnail")
USERS = {
    "admin": ("a1220000-0000-0000-0000-00000000a001", "etl-admin", "admin"),
    "haushalt": ("a1220000-0000-0000-0000-00000000a002", "etl-haushalt", "haushalt"),
    "guest": ("a1220000-0000-0000-0000-00000000a003", "etl-guest", "guest"),
}


def _load_registry():
    name = "registry_app"
    if name not in sys.modules:
        d = AUTOMATIONS / "alice-source-registry" / "app"
        spec = importlib.util.spec_from_file_location(name, d / "__init__.py", submodule_search_locations=[str(d)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return (importlib.import_module(f"{name}.main"), importlib.import_module(f"{name}.service"),
            importlib.import_module(f"{name}.config"))


# ---------------------------------------------------------------- JWT
@pytest.fixture(scope="session")
def keys(tmp_path_factory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    path = tmp_path_factory.mktemp("keys") / "jwt_public.pem"
    path.write_bytes(pub)
    return priv, str(path)


def make_token(priv, user_id: str, role: str, exp_in: int = 3600) -> str:
    now = int(time.time())
    return jwt.encode({"user_id": user_id, "username": "x", "role": role, "iat": now, "exp": now + exp_in},
                      priv, algorithm="RS256")


# ---------------------------------------------------------------- fake PROJ-120
class FakeRebuild:
    """alice-etl-rebuild with fixed data. `down` = not reachable (503)."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.down = False
        self.run: dict | None = None
        self.runs: list[dict] = []
        self.results: list[dict] = []
        self.reconciliation_running: int | None = None
        self.reject: dict[str, tuple[int, dict]] = {}
        self.app = FastAPI()

        @self.app.middleware("http")
        async def record(request: Request, call_next):
            body = None
            if request.method == "POST":
                raw = await request.body()
                body = json.loads(raw) if raw else None
            self.calls.append((request.method, request.url.path, body))
            if self.down:
                return JSONResponse(status_code=503, content={"detail": "down"})
            key = f"{request.method} {request.url.path}"
            if key in self.reject:
                st, b = self.reject[key]
                return JSONResponse(status_code=st, content=b)
            return await call_next(request)

        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "reconciliation_running": self.reconciliation_running}

        @self.app.get("/rebuilds/current")
        async def current():
            if self.run is None:
                return JSONResponse(status_code=404, content={"error": "not_found", "detail": "Noch kein Lauf"})
            return self.run

        @self.app.get("/rebuilds")
        async def runs():
            return {"total": len(self.runs), "items": self.runs}

        @self.app.get("/rebuilds/{rid}")
        async def run(rid: int):
            return self.run

        @self.app.post("/rebuilds")
        async def start(request: Request):
            b = await request.json()
            self.run = {"id": 7, "status": "running", "status_de": "läuft", "start_stage": b["start_stage"],
                        "kind": b["kind"], "started_by": b["started_by"], "in_run": 0, "finished": 0}
            return JSONResponse(status_code=201, content=self.run)

        @self.app.post("/rebuilds/{rid}/{action}")
        async def control(rid: int, action: str):
            self.run = {**(self.run or {"id": rid}),
                        "status": {"pause": "paused", "resume": "running", "cancel": "cancelled"}[action]}
            return self.run

        @self.app.get("/rebuilds/{rid}/errors")
        async def errors(rid: int):
            return {"total": 2, "items": [{"id": "aaaaaaaaaaaa", "title": "A", "stage": "extract", "error": "x"},
                                          {"id": "bbbbbbbbbbbb", "title": "B", "stage": "classify", "error": "y"}]}

        @self.app.post("/reconcile")
        async def reconcile():
            return JSONResponse(status_code=202, content={"id": 1, "kind": "on_demand", "mode": "levels"})

        @self.app.post("/reconcile/full-rehash")
        async def rehash():
            return JSONResponse(status_code=202, content={"id": 2, "kind": "on_demand", "mode": "full_rehash"})

        @self.app.get("/reconcile/results")
        async def results():
            return {"total": len(self.results), "items": self.results}

        @self.app.get("/reconcile/results/{rid}")
        async def result(rid: int):
            return next(r for r in self.results if r["id"] == rid)

        @self.app.get("/reconcile/results/{rid}/gaps")
        async def gaps(rid: int, level: int | None = None):
            return {"total": 0, "items": [], "level": level}


# ---------------------------------------------------------------- environment
class Env:
    async def execute(self, sql, *args):
        async with self.pool.acquire() as con:
            return await con.execute(sql, *args)

    async def fetch(self, sql, *args):
        async with self.pool.acquire() as con:
            return await con.fetch(sql, *args)

    async def fetchval(self, sql, *args):
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, *args)

    def headers(self, role="admin"):
        uid, _, r = USERS[role]
        return {"Authorization": f"Bearer {make_token(self.priv, uid, r)}"}

    async def get(self, path, role="admin", **params):
        return await self.http.get(path, headers=self.headers(role), params=params)

    async def post(self, path, role="admin", json=None):
        return await self.http.post(path, headers=self.headers(role), json=json)

    async def source(self, n: int, kind="document", title=None, deleted=False, locked=None, states=None,
                     error=None, attempts=0, at=None):
        """Source t<n> (id 12 chars) with a state per stage (default: all done)."""
        sid = f"t{n:011d}"
        await self.execute(
            "INSERT INTO alice.sources (id, kind, hash, title, path, deleted, repo_error, repo_error_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, CASE WHEN $7::text IS NULL THEN NULL ELSE COALESCE($8, NOW()) END)",
            sid, kind, f"sha256:{n:020d}", title if title is not None else f"Dokument {n}",
            f"{kind}s/2026/11/{sid}.md", deleted, locked, at)
        states = states or {}
        await self.execute(
            "INSERT INTO alice.source_stages (source_id, stage, state, attempts, last_error, last_attempt_at, "
            "next_retry_at) SELECT $1, ps.name, COALESCE(($2::jsonb)->>ps.name, 'done'), "
            "CASE WHEN ($2::jsonb) ? ps.name THEN $4 ELSE 0 END, "
            "CASE WHEN ($2::jsonb)->>ps.name LIKE 'failed%' THEN $3 END, COALESCE($5, NOW()), "
            "CASE WHEN ($2::jsonb)->>ps.name = 'failed' THEN NOW() + interval '5 minutes' END "
            "FROM alice.pipeline_stages ps",
            sid, json.dumps(states), error or "Fehler", attempts, at)
        return sid


@pytest.fixture
def settings(keys):
    return Settings(postgres_dsn=DSN or "", jwt_public_key_path=keys[1], registry_url="http://registry",
                    rebuild_url="http://rebuild", retry_limit=1000)


@pytest.fixture
async def env(tmp_path, settings, keys):
    if not DSN:
        pytest.skip("TEST_POSTGRES_DSN not set")
    import asyncpg

    rmain, rservice, rconfig = _load_registry()
    pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=20)
    async with pool.acquire() as con:
        await con.execute("TRUNCATE alice.sources, alice.doc_documents CASCADE")
        await con.execute("DELETE FROM alice.pipeline_stages WHERE NOT (name = ANY($1::text[]))", list(DEFAULT_STAGES))
        for uid, name, role in USERS.values():
            await con.execute("INSERT INTO alice.users (id, username, role, is_active) VALUES ($1::uuid, $2, $3, TRUE) "
                              "ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role, is_active = TRUE", uid, name, role)
    repo = tmp_path / "sot"
    repo.mkdir()
    reg = rservice.Registry(rconfig.Settings(repo_path=str(repo), postgres_dsn=DSN), pool, None)
    await reg.startup()
    rmain.app.state.reg = reg
    rhttp = httpx.AsyncClient(transport=httpx.ASGITransport(app=rmain.app), base_url="http://registry")
    fake = FakeRebuild()
    fhttp = httpx.AsyncClient(transport=httpx.ASGITransport(app=fake.app), base_url="http://rebuild")
    svc = main.Service(settings, pool, Client("Register", "http://registry", 30, client=rhttp),
                       Client("Neuaufbau/Abgleich-Dienst", "http://rebuild", 3, client=fhttp))
    main.app.state.svc = svc
    e = Env()
    e.pool, e.priv, e.fake, e.svc, e.reg = pool, keys[0], fake, svc, reg
    e.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://etl")
    yield e
    await e.http.aclose()
    await rhttp.aclose()
    await fhttp.aclose()
    async with pool.acquire() as con:
        await con.execute("DELETE FROM alice.users WHERE id = ANY($1::uuid[])", [u[0] for u in USERS.values()])
    await pool.close()


