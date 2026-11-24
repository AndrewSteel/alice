"""
alice-etl-rebuild — rebuild runs and completeness reconciliation of the new ETL (PROJ-120).

Internal HTTP interface for PROJ-122, only reachable inside the Docker network: there is
deliberately no nginx route and no end-user access.

Endpoints:
  GET  /health
  POST /rebuilds                        start a rebuild (start_stage, optional kind, started_by); 409 if one is active
  GET  /rebuilds?limit=&offset=         runs, newest first, with their numbers
  GET  /rebuilds/current                progress of the active run (else the latest run)
  GET  /rebuilds/{id}                   progress (from memory for active runs)
  POST /rebuilds/{id}/pause|resume|cancel
  GET  /rebuilds/{id}/errors?limit=&offset=
  POST /reconcile                       reconciliation on demand (levels 1–4); 409 if one is running
  POST /reconcile/full-rehash           full re-hash of the originals on demand
  GET  /reconcile/results?limit=&offset=
  GET  /reconcile/results/{id}
  GET  /reconcile/results/{id}/gaps?level=&limit=&offset=
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .clients import DetectionClient, RegistryClient
from .config import Settings
from .rebuild import KINDS, Invalid, NotFound, Rebuilds, Rejected
from .reconcile import Busy409, Reconciler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("alice-etl-rebuild")

TICK_STALE_SECONDS = 120
STAGE_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"


class Service:
    def __init__(self, settings: Settings, pool, registry: RegistryClient, detection: DetectionClient):
        self.s = settings
        self.pool = pool
        self.registry = registry
        self.detection = detection
        self.rebuilds = Rebuilds(settings, pool, registry)
        self.reconciler = Reconciler(settings, pool, registry, detection)
        self.rebuilds.on_done = self._after_rebuild
        self.last_tick = time.monotonic()

    def _after_rebuild(self, run_id: int) -> None:
        # started by the next tick of the reconciler (also after a restart, AK-17)
        logger.info("Rebuild run %d finished: reconciliation follows", run_id)

    async def tick(self) -> None:
        try:
            await self.rebuilds.tick()
        except Exception:
            logger.exception("rebuild tick failed")
        try:
            await self.reconciler.tick()
        except Exception as exc:
            logger.warning("reconciliation schedule check failed: %s", exc)
        self.last_tick = time.monotonic()


async def _loop(svc: Service) -> None:
    while True:
        await svc.tick()
        await asyncio.sleep(svc.s.tick_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    if not settings.postgres_dsn:
        raise RuntimeError("POSTGRES_DSN is not set")
    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=10)
    registry = RegistryClient(settings.registry_url, settings.http_timeout_seconds)
    detection = DetectionClient(settings.detection_url, settings.http_timeout_seconds)
    svc = Service(settings, pool, registry, detection)
    n = await svc.reconciler.mark_interrupted()
    if n:
        logger.warning("%d interrupted reconciliation(s) marked as incomplete", n)
    app.state.svc = svc
    loop = asyncio.create_task(_loop(svc))
    try:
        yield
    finally:
        loop.cancel()
        if svc.reconciler.task and not svc.reconciler.task.done():
            svc.reconciler.task.cancel()
        await registry.close()
        await detection.close()
        await pool.close()


app = FastAPI(title="alice-etl-rebuild", version="1.0.0", lifespan=lifespan)


def _svc(request: Request) -> Service:
    return request.app.state.svc


def _error(status: int, code: str, detail: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail, **extra})


@app.exception_handler(NotFound)
async def _nf(_, exc):
    return _error(404, "not_found", str(exc))


@app.exception_handler(Invalid)
async def _inv(_, exc):
    return _error(422, "invalid", str(exc))


@app.exception_handler(Rejected)
async def _rej(_, exc):
    return _error(409, "conflict", str(exc), **({"run": jsonable_encoder(exc.run)} if exc.run else {}))


@app.exception_handler(Busy409)
async def _busy(_, exc):
    return _error(409, "busy", str(exc))


# ---------------------------------------------------------------- models
class StartIn(BaseModel):
    start_stage: str = Field(..., pattern=STAGE_PATTERN)
    kind: str | None = Field(None, pattern="^(" + "|".join(KINDS) + ")$")
    started_by: str = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------- routes
@app.get("/health")
async def health(request: Request):
    svc = _svc(request)
    errors, warnings = [], []
    try:
        await svc.pool.fetchval("SELECT 1")
    except Exception as exc:
        errors.append(f"Datenbank nicht erreichbar: {exc.__class__.__name__}")
    if time.monotonic() - svc.last_tick > TICK_STALE_SECONDS:
        errors.append("Hintergrund-Schleife läuft nicht")
    for p in svc.rebuilds.cache.values():
        if p["status"] == "waiting":
            warnings.append(f"Neuaufbau-Lauf {p['id']} wartet: {p['reason']}")
    status = "unhealthy" if errors else ("warning" if warnings else "healthy")
    return JSONResponse(status_code=503 if errors else 200, content={
        "status": status, "errors": errors, "warnings": warnings,
        "active_rebuild": min(svc.rebuilds.cache) if svc.rebuilds.cache else None,
        "reconciliation_running": svc.reconciler.current if svc.reconciler.running else None})


@app.post("/rebuilds")
async def start_rebuild(body: StartIn, request: Request):
    progress = await _svc(request).rebuilds.start(body.start_stage, body.kind, body.started_by)
    return JSONResponse(status_code=201, content=progress)


@app.get("/rebuilds")
async def list_rebuilds(request: Request, limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0)):
    return await _svc(request).rebuilds.list_runs(limit, offset)


@app.get("/rebuilds/current")
async def current_rebuild(request: Request):
    reb = _svc(request).rebuilds
    rid = await reb.current_id()
    if rid is None:
        raise NotFound("Noch kein Neuaufbau-Lauf")
    return await reb.progress(rid)


@app.get("/rebuilds/{run_id}")
async def get_rebuild(run_id: int, request: Request):
    return await _svc(request).rebuilds.progress(run_id)


@app.post("/rebuilds/{run_id}/{action}")
async def control(run_id: int, action: str, request: Request):
    if action not in ("pause", "resume", "cancel"):
        raise NotFound("Aktion ist pause, resume oder cancel")
    return await _svc(request).rebuilds.control(run_id, action)


@app.get("/rebuilds/{run_id}/errors")
async def run_errors(run_id: int, request: Request, limit: int = Query(100, ge=1, le=1000),
                     offset: int = Query(0, ge=0)):
    return await _svc(request).rebuilds.errors(run_id, limit, offset)


@app.post("/reconcile")
async def reconcile_now(request: Request):
    rid = await _svc(request).reconciler.start("on_demand")
    return JSONResponse(status_code=202, content={"id": rid, "kind": "on_demand", "mode": "levels"})


@app.post("/reconcile/full-rehash")
async def full_rehash(request: Request):
    rid = await _svc(request).reconciler.start("on_demand", "full_rehash")
    return JSONResponse(status_code=202, content={"id": rid, "kind": "on_demand", "mode": "full_rehash"})


@app.get("/reconcile/results")
async def results(request: Request, limit: int = Query(30, ge=1, le=500), offset: int = Query(0, ge=0)):
    return await _svc(request).reconciler.list_results(limit, offset)


@app.get("/reconcile/results/{result_id}")
async def result(result_id: int, request: Request):
    r = await _svc(request).reconciler.get_result(result_id)
    if r is None:
        raise NotFound(f"Ergebnis {result_id} unbekannt")
    return r


@app.get("/reconcile/results/{result_id}/gaps")
async def gaps(result_id: int, request: Request, level: int | None = Query(None, ge=1, le=4),
               limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    return await _svc(request).reconciler.gaps(result_id, level, limit, offset)
