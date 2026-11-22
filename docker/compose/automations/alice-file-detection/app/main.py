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

from .config import Settings
from .detector import Busy, Detector
from .registry import RegistryClient

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
