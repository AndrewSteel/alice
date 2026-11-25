"""
alice-file-detection — finds the originals in the watched NAS folders and keeps
the source register (alice-source-registry, PROJ-115) in sync with them (PROJ-116).

Internal HTTP interface, only reachable inside the Docker network: there is
deliberately no nginx route and no end-user access.

Endpoints:
  GET  /health                   healthy / warning (skipped folder, register paused) / unhealthy
  POST /runs/day                 start a day scan now (409 busy if a run is active)
  POST /runs/night               start a nightly run now (409 busy if a run is active)
  GET  /runs?kind=night&limit=   recent runs incl. the nightly summaries
  GET  /runs/{id}                one run
  GET  /problems?limit=          open detection problems
  PROJ-120 (level 1 of the reconciliation, called by alice-etl-rebuild):
  POST /reconcile/lease          take / renew the reconciliation lease (no nightly run meanwhile)
  DELETE /reconcile/lease/{token}
  POST /reconcile/check          NAS <-> register, read only
  POST /reconcile/register       register unregistered files
  POST /reconcile/rehash         rolling re-hash (portion) or full re-hash, read only
  POST /reconcile/apply          apply differing hashes (original changed in place)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime

import asyncpg
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from pydantic import BaseModel, Field

from . import reconcile
from .config import Settings
from .detector import Busy, Detector
from .registry import RegistryClient, RegistryUnavailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("alice-file-detection")

TICK_SECONDS = 5
TICK_STALE_SECONDS = 120


async def _scheduler(det: Detector) -> None:
    while True:
        try:
            await det.tick()
        except Exception:
            logger.exception("scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    if not settings.postgres_dsn:
        raise RuntimeError("POSTGRES_DSN is not set")
    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=5)
    registry = RegistryClient(settings.registry_url, settings.registry_timeout_seconds)
    det = Detector(settings, pool, registry)
    aborted = await det.mark_aborted()
    if aborted:
        logger.warning("%d interrupted run(s) marked as aborted", aborted)
    app.state.det = det
    scheduler = asyncio.create_task(_scheduler(det))
    try:
        yield
    finally:
        scheduler.cancel()
        if det.task and not det.task.done():
            det.task.cancel()
        await registry.close()
        await pool.close()


app = FastAPI(title="alice-file-detection", version="1.0.0", lifespan=lifespan)


@app.exception_handler(RegistryUnavailable)
async def _registry_down(_, exc):
    return JSONResponse(status_code=503, content={"error": "registry_unavailable", "detail": str(exc)})


def _det(request: Request) -> Detector:
    return request.app.state.det


def _plain(row) -> dict:
    out = {}
    for k, v in dict(row).items():
        if isinstance(v, datetime):
            v = v.isoformat()
        elif isinstance(v, str) and k == "summary":
            v = json.loads(v)
        out[k] = v
    return out


@app.get("/health")
async def health(request: Request):
    det = _det(request)
    errors = []
    try:
        await det.pool.fetchval("SELECT 1")
    except Exception as exc:
        errors.append(f"Datenbank nicht erreichbar: {exc}")
    if time.monotonic() - det.last_tick > TICK_STALE_SECONDS:
        errors.append("Zeitplaner läuft nicht")
    warnings = [f"Überwachter Ordner übersprungen: {f} ({r})" for f, r in sorted(det.warnings.items())]
    if det.paused_reason:
        warnings.append(f"Erkennung pausiert: {det.paused_reason}")
    status = "unhealthy" if errors else ("warning" if warnings else "healthy")
    body = {"status": status, "running": det.running, "errors": errors, "warnings": warnings}
    return JSONResponse(status_code=503 if errors else 200, content=body)


@app.post("/runs/{kind}")
async def start_run(kind: str, request: Request):
    if kind not in ("day", "night"):
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": "Lauf ist 'day' oder 'night'"})
    det = _det(request)
    try:
        det.start(kind, "manual")
    except Busy as exc:
        return JSONResponse(status_code=409, content={"error": "busy", "detail": f"Lauf aktiv: {exc}",
                                                      "running": str(exc)})
    return JSONResponse(status_code=202, content={"started": kind})


@app.get("/runs")
async def list_runs(request: Request, kind: str | None = Query(None, pattern="^(day|night)$"),
                    limit: int = Query(20, ge=1, le=500)):
    async with _det(request).pool.acquire() as con:
        rows = await con.fetch("SELECT id, kind, trigger, state, started_at, finished_at, error, summary "
                               "FROM alice.detect_runs WHERE ($1::text IS NULL OR kind = $1) "
                               "ORDER BY started_at DESC, id DESC LIMIT $2", kind, limit)
    return {"runs": [_plain(r) for r in rows]}


@app.get("/runs/{run_id}")
async def get_run(run_id: int, request: Request):
    async with _det(request).pool.acquire() as con:
        row = await con.fetchrow("SELECT id, kind, trigger, state, started_at, finished_at, error, summary "
                                 "FROM alice.detect_runs WHERE id = $1", run_id)
    if not row:
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": f"Lauf {run_id} unbekannt"})
    return _plain(row)


@app.get("/problems")
async def problems(request: Request, limit: int = Query(500, ge=1, le=10000)):
    items, count = await _det(request).problems(limit)
    return {"count": count, "items": items}


# ---------------------------------------------------------------- PROJ-120
class LeaseIn(BaseModel):
    token: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    seconds: int = Field(300, ge=10, le=3600)


class FileIn(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)


class RegisterIn(BaseModel):
    items: list[FileIn] = Field(..., min_length=1, max_length=100000)


class RehashIn(BaseModel):
    full: bool = False
    cycle_days: float = Field(30, gt=0, le=3650)
    max_seconds: float | None = Field(None, gt=0)
    max_bytes: int | None = Field(None, gt=0)


class ApplyIn(BaseModel):
    paths: list[str] = Field(..., min_length=1, max_length=100000)


def _busy(exc) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": "busy", "detail": f"Lauf aktiv: {exc}", "running": str(exc)})


@app.post("/reconcile/lease")
async def lease(body: LeaseIn, request: Request):
    try:
        token = reconcile.acquire_lease(_det(request), body.token, body.seconds)
    except Busy as exc:
        return _busy(exc)
    except reconcile.LeaseHeld as exc:
        return JSONResponse(status_code=409, content={"error": "lease_held", "detail": str(exc)})
    return {"token": token, "seconds": body.seconds}


@app.delete("/reconcile/lease/{token}")
async def unlease(token: str, request: Request):
    return {"released": reconcile.release_lease(_det(request), token)}


@app.post("/reconcile/check")
async def rc_check(request: Request):
    try:
        return await reconcile.check(_det(request))
    except Busy as exc:
        return _busy(exc)


@app.post("/reconcile/register")
async def rc_register(body: RegisterIn, request: Request):
    try:
        return await reconcile.register(_det(request), [i.model_dump() for i in body.items])
    except Busy as exc:
        return _busy(exc)


@app.post("/reconcile/rehash")
async def rc_rehash(body: RehashIn, request: Request):
    return await reconcile.rehash(_det(request), full=body.full, cycle_days=body.cycle_days,
                                  max_seconds=body.max_seconds, max_bytes=body.max_bytes)


@app.post("/reconcile/apply")
async def rc_apply(body: ApplyIn, request: Request):
    try:
        return await reconcile.apply(_det(request), body.paths)
    except Busy as exc:
        return _busy(exc)
