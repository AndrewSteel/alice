"""
alice-etl-status — admin interface of the WebApp to the new ETL (PROJ-122).

Reached by nginx under /api/etl/ → /etl/... Every route except /health needs an active user with
the role admin (JWT + role from alice.users): 401 without/invalid token, 403 otherwise.

Endpoints:
  GET  /health
  GET  /etl/state?kind=&include_deleted=          summary, matrix stage × state, rebuild + reconciliation
  GET  /etl/sources?stage=&state=&kind=&deleted=&locked=&q=&limit=&offset=
  GET  /etl/sources/{id}                          detail: stages, locations, events, markdown path
  POST /etl/sources/{id}/stages/{stage}/retry
  GET  /etl/errors?stage=&state=&kind=&limit=&offset=
  POST /etl/retry                                 bulk retry of a list/error selection (dry_run for the dialog)
  GET  /etl/rebuild/preview?start_stage=&kind=
  POST /etl/rebuilds                              start (started_by = the admin)
  GET  /etl/rebuilds, /etl/rebuilds/{id}, /etl/rebuilds/{id}/errors
  POST /etl/rebuilds/{id}/pause|resume|cancel
  POST /etl/reconcile, /etl/reconcile/full-rehash
  GET  /etl/reconcile/results, /etl/reconcile/results/{id}, /etl/reconcile/results/{id}/gaps
"""
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

import asyncpg
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from . import queries, retry
from .auth import Auth, Forbidden, Unauthorized
from .config import Settings
from .upstream import Client, Rejected, Unavailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("alice-etl-status")
logging.getLogger("httpx").setLevel(logging.WARNING)

STAGE_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
ID_PATTERN = r"^[a-z0-9]{12}$"
KIND_PATTERN = "^(" + "|".join(queries.KINDS) + ")$"
STATE_PATTERN = "^(" + "|".join(queries.STATES) + ")$"
ACTIVE_RUN = ("running", "paused", "waiting")
STALE_HOURS = 36


class Service:
    def __init__(self, settings: Settings, pool, registry: Client, rebuild: Client):
        self.s = settings
        self.pool = pool
        self.registry = registry
        self.rebuild = rebuild
        self.auth = Auth(settings.jwt_public_key_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    if not settings.postgres_dsn:
        raise RuntimeError("POSTGRES_DSN is not set")
    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=10)
    registry = Client("Register", settings.registry_url, settings.http_timeout_seconds)
    rebuild = Client("Neuaufbau/Abgleich-Dienst", settings.rebuild_url, settings.http_timeout_seconds)
    app.state.svc = Service(settings, pool, registry, rebuild)
    try:
        yield
    finally:
        await registry.close()
        await rebuild.close()
        await pool.close()


app = FastAPI(title="alice-etl-status", version="1.0.0", lifespan=lifespan)


def _svc(request: Request) -> Service:
    return request.app.state.svc


def _error(status: int, code: str, detail: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail, **extra})


@app.exception_handler(Unauthorized)
async def _unauth(_, exc):
    return _error(401, "unauthorized", str(exc))


@app.exception_handler(Forbidden)
async def _forbidden(_, exc):
    return _error(403, "forbidden", str(exc))


@app.exception_handler(Unavailable)
async def _unavailable(_, exc):
    return _error(503, "service_unavailable", str(exc), service="rebuild" if exc.service.startswith("Neu")
                  else "register")


@app.exception_handler(Rejected)
async def _rejected(_, exc):
    body = {"error": exc.body.get("error") or "rejected", "detail": str(exc)}
    return JSONResponse(status_code=exc.status, content=body)


@app.exception_handler(retry.NotRetryable)
async def _not_retryable(_, exc):
    return _error(409, "not_retryable", str(exc), reason=exc.reason, state=exc.state)


@app.exception_handler(retry.LimitExceeded)
async def _limit(_, exc):
    return _error(409, "limit_exceeded", str(exc), count=exc.count, limit=exc.limit)


@app.exception_handler(retry.SourceNotFound)
async def _nf(_, exc):
    return _error(404, "not_found", str(exc))


@app.exception_handler(ValidationError)
async def _invalid(_, exc):
    return _error(422, "invalid", "; ".join(e.get("msg", "") for e in exc.errors()))


@app.exception_handler(asyncpg.PostgresError)
@app.exception_handler(OSError)
async def _db(_, exc):
    logger.warning("database error: %s", exc.__class__.__name__)
    return _error(503, "service_unavailable", "Datenbank nicht erreichbar", service="register")


async def admin(request: Request, authorization: str | None = Header(default=None)) -> dict:
    svc = _svc(request)
    return await svc.auth.admin(svc.pool, authorization)


# ---------------------------------------------------------------- health
@app.get("/health")
async def health(request: Request):
    svc = _svc(request)
    errors = []
    try:
        await svc.pool.fetchval("SELECT 1")
    except Exception as exc:
        errors.append(f"Datenbank nicht erreichbar: {exc.__class__.__name__}")
    try:
        svc.auth.key()
    except Exception as exc:
        errors.append(f"JWT-Schlüssel nicht lesbar: {exc.__class__.__name__}")
    return JSONResponse(status_code=503 if errors else 200,
                        content={"status": "unhealthy" if errors else "healthy", "errors": errors})


# ---------------------------------------------------------------- state
def _age_hours(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    return (now - datetime.fromisoformat(ts)).total_seconds() / 3600


def reported_gaps(result: dict | None) -> int:
    levels = ((result or {}).get("summary") or {}).get("levels") or {}
    return sum(int(v.get("reported", 0)) + int(v.get("repair_failed", 0)) for v in levels.values())


def needs_attention(result: dict | None, now: datetime) -> bool:
    """Reconciliation summary is highlighted: none, incomplete or older than 36 h (AK-30)."""
    if not result:
        return True
    age = _age_hours(result.get("finished_at") or result.get("started_at"), now)
    return result.get("state") != "complete" or age is None or age > STALE_HOURS


def traffic_light(result: dict | None, serious: int, now: datetime) -> str:
    """Dashboard tile (AK-37): red = no/incomplete/stale reconciliation; yellow = failed_permanent or
    locked sources, or gaps only reported; else green."""
    if needs_attention(result, now):
        return "red"
    if serious > 0 or reported_gaps(result) > 0:
        return "yellow"
    return "green"


def run_percent(p: dict | None) -> int | None:
    if not p:
        return None
    in_run = p.get("in_run") or 0
    return 100 if in_run == 0 else int(p.get("finished", 0) * 100 // in_run)


async def _rebuild_state(svc: Service) -> dict:
    """Current/last run, last finished reconciliation and running reconciliation from PROJ-120."""
    t = svc.s.state_timeout_seconds

    async def current():
        try:
            return await svc.rebuild.call("GET", "/rebuilds/current", timeout=t)
        except Rejected as exc:
            if exc.status == 404:
                return None
            raise

    health, run, results = await asyncio.gather(
        svc.rebuild.call("GET", "/health", timeout=t, ok_5xx=True), current(),
        svc.rebuild.call("GET", "/reconcile/results", params={"limit": 10}, timeout=t))
    last = next((r for r in results.get("items", []) if r.get("state") != "running"), None)
    return {"run": run, "last_reconcile": last, "reconcile_running": health.get("reconciliation_running")}


@app.get("/etl/state")
async def state(request: Request, user: dict = Depends(admin),
                kind: str | None = Query(None, pattern=KIND_PATTERN), include_deleted: bool = False):
    svc = _svc(request)
    now = datetime.now(timezone.utc)
    async with svc.pool.acquire() as con:
        st = await queries.stages(con)
        mx = await queries.matrix(con, kind, include_deleted)
        cnt = await queries.counts(con)
    try:
        rb = await _rebuild_state(svc)
        rb_ok = True
    except (Unavailable, Rejected) as exc:
        logger.info("PROJ-120 service: %s", exc)
        rb, rb_ok = {"run": None, "last_reconcile": None, "reconcile_running": None}, False
    run = rb["run"]
    last = rb["last_reconcile"]
    return {
        "as_of": now.isoformat(),
        "user": user["name"],
        "services": {"register": True, "rebuild": rb_ok},
        "retry_limit": svc.s.retry_limit,
        "stages": [s["name"] for s in st],
        "matrix": {s["name"]: mx.get(s["name"], {x: 0 for x in queries.STATES}) for s in st},
        "counts": cnt,
        "rebuild": {"run": run, "active": bool(run and run.get("status") in ACTIVE_RUN),
                    "percent": run_percent(run)} if rb_ok else None,
        "reconcile": {"last": last, "running": rb["reconcile_running"],
                      "attention": needs_attention(last, now), "reported_gaps": reported_gaps(last)}
        if rb_ok else None,
        "light": traffic_light(last, cnt["serious"], now) if rb_ok else None,
    }


# ---------------------------------------------------------------- sources + errors
class ListFilter(BaseModel):
    stage: str = Field(..., pattern=STAGE_PATTERN)
    state: str | None = Field(None, pattern=STATE_PATTERN)
    kind: str | None = Field(None, pattern=KIND_PATTERN)
    deleted: Literal["no", "yes", "all"] = "no"
    locked: Literal["all", "yes", "no"] = "all"
    q: str | None = Field(None, max_length=200)


class ErrorFilter(BaseModel):
    stage: str | None = Field(None, pattern=STAGE_PATTERN)
    state: Literal["failed", "failed_permanent", "locked"] | None = None
    kind: str | None = Field(None, pattern=KIND_PATTERN)


@app.get("/etl/sources")
async def sources(request: Request, user: dict = Depends(admin), f: ListFilter = Depends(),
                  limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    async with _svc(request).pool.acquire() as con:
        return await queries.source_list(con, f.model_dump(), limit, offset)


@app.get("/etl/sources/{source_id}")
async def source(source_id: str, request: Request, user: dict = Depends(admin)):
    if not re.fullmatch(ID_PATTERN, source_id):
        raise retry.SourceNotFound(f"Quelle {source_id} unbekannt")
    async with _svc(request).pool.acquire() as con:
        d = await queries.source_detail(con, source_id)
    if d is None:
        raise retry.SourceNotFound(f"Quelle {source_id} unbekannt")
    return d


@app.post("/etl/sources/{source_id}/stages/{stage}/retry")
async def retry_stage(source_id: str, stage: str, request: Request, user: dict = Depends(admin)):
    if not re.fullmatch(ID_PATTERN, source_id) or not re.fullmatch(STAGE_PATTERN, stage):
        raise retry.SourceNotFound(f"Stufe {stage} der Quelle {source_id} unbekannt")
    svc = _svc(request)
    return await retry.retry_one(svc.pool, svc.registry, source_id, stage, user["name"])


@app.get("/etl/errors")
async def error_list(request: Request, user: dict = Depends(admin), f: ErrorFilter = Depends(),
                     limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    async with _svc(request).pool.acquire() as con:
        return await queries.errors(con, f.model_dump(), limit, offset)


class BulkIn(BaseModel):
    scope: Literal["sources", "errors"]
    filter: dict
    dry_run: bool = False


@app.post("/etl/retry")
async def bulk_retry(body: BulkIn, request: Request, user: dict = Depends(admin)):
    svc = _svc(request)
    if body.scope == "sources":
        f = ListFilter(**body.filter).model_dump()
        fn = lambda con: queries.list_targets(con, f)  # noqa: E731
    else:
        f = ErrorFilter(**body.filter).model_dump()
        fn = lambda con: queries.error_targets(con, f)  # noqa: E731
    return await retry.retry_bulk(svc.pool, svc.registry, fn, svc.s.retry_limit, user["name"], body.dry_run,
                                  svc.s.retry_parallel)


# ---------------------------------------------------------------- rebuild (PROJ-120)
class StartIn(BaseModel):
    start_stage: str = Field(..., pattern=STAGE_PATTERN)
    kind: str | None = Field(None, pattern=KIND_PATTERN)


@app.get("/etl/rebuild/preview")
async def rebuild_preview(request: Request, user: dict = Depends(admin),
                          start_stage: str = Query(..., pattern=STAGE_PATTERN),
                          kind: str | None = Query(None, pattern=KIND_PATTERN)):
    async with _svc(request).pool.acquire() as con:
        p = await queries.rebuild_preview(con, start_stage, kind)
    if p is None:
        return _error(422, "invalid", f"{start_stage} ist keine wählbare Startstufe")
    return p


@app.post("/etl/rebuilds")
async def start_rebuild(body: StartIn, request: Request, user: dict = Depends(admin)):
    res = await _svc(request).rebuild.call("POST", "/rebuilds", json={
        "start_stage": body.start_stage, "kind": body.kind, "started_by": user["name"]})
    logger.info("Rebuild started by %s from %s (%s)", user["name"], body.start_stage, body.kind or "all")
    return JSONResponse(status_code=201, content=res)


@app.get("/etl/rebuilds")
async def rebuilds(request: Request, user: dict = Depends(admin), limit: int = Query(20, ge=1, le=200),
                   offset: int = Query(0, ge=0)):
    return await _svc(request).rebuild.call("GET", "/rebuilds", params={"limit": limit, "offset": offset})


@app.get("/etl/rebuilds/{run_id}")
async def rebuild(run_id: int, request: Request, user: dict = Depends(admin)):
    return await _svc(request).rebuild.call("GET", f"/rebuilds/{run_id}")


@app.post("/etl/rebuilds/{run_id}/{action}")
async def control(run_id: int, action: Literal["pause", "resume", "cancel"], request: Request,
                  user: dict = Depends(admin)):
    res = await _svc(request).rebuild.call("POST", f"/rebuilds/{run_id}/{action}")
    logger.info("Rebuild %d: %s by %s", run_id, action, user["name"])
    return res


@app.get("/etl/rebuilds/{run_id}/errors")
async def run_errors(run_id: int, request: Request, user: dict = Depends(admin),
                     limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return await _svc(request).rebuild.call("GET", f"/rebuilds/{run_id}/errors",
                                            params={"limit": limit, "offset": offset})


# ---------------------------------------------------------------- reconciliation (PROJ-120)
@app.post("/etl/reconcile")
async def reconcile_now(request: Request, user: dict = Depends(admin)):
    res = await _svc(request).rebuild.call("POST", "/reconcile")
    logger.info("Reconciliation on demand by %s", user["name"])
    return JSONResponse(status_code=202, content=res)


@app.post("/etl/reconcile/full-rehash")
async def full_rehash(request: Request, user: dict = Depends(admin)):
    res = await _svc(request).rebuild.call("POST", "/reconcile/full-rehash")
    logger.info("Full re-hash by %s", user["name"])
    return JSONResponse(status_code=202, content=res)


@app.get("/etl/reconcile/results")
async def results(request: Request, user: dict = Depends(admin), limit: int = Query(20, ge=1, le=200),
                  offset: int = Query(0, ge=0)):
    return await _svc(request).rebuild.call("GET", "/reconcile/results", params={"limit": limit, "offset": offset})


@app.get("/etl/reconcile/results/{result_id}")
async def result(result_id: int, request: Request, user: dict = Depends(admin)):
    return await _svc(request).rebuild.call("GET", f"/reconcile/results/{result_id}")


@app.get("/etl/reconcile/results/{result_id}/gaps")
async def gaps(result_id: int, request: Request, user: dict = Depends(admin),
               level: int | None = Query(None, ge=1, le=9), limit: int = Query(100, ge=1, le=500),
               offset: int = Query(0, ge=0)):
    return await _svc(request).rebuild.call("GET", f"/reconcile/results/{result_id}/gaps",
                                            params={"level": level, "limit": limit, "offset": offset})
