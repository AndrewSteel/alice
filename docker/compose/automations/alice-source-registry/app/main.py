"""
alice-source-registry — source-of-truth repo + source register (PROJ-115).

Internal HTTP interface for the ETL stages (PROJ-116 ff.). Only reachable inside
the Docker network: there is deliberately no nginx route and no end-user access.

Endpoints:
  GET  /health
  POST /sources                                   register a source (or add a location to a known hash)
  GET  /sources?hash=...                          look up by hash
  GET  /sources/{id}                              register entry incl. locations, parents, children, stages
  GET  /sources/{id}/document                     frontmatter + content of the source markdown
  PUT  /sources/{id}/document                     a stage writes fields / content (commit or batch)
  POST /sources/{id}/locations                    location added / changed
  POST /sources/{id}/locations/gone               location disappeared
  PUT  /sources/{id}/original                     original changed in place (hash, size, modified)
  GET  /stages, POST /stages                      list / add pipeline stages
  POST /stages/{stage}/claim                      take over due work exclusively
  POST /sources/{id}/stages/{stage}/done|fail|release|retry
  POST /maintenance/scan|flush|resync-queue       run background jobs now
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import asyncpg
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from . import markdown as md
from .config import Settings
from .gitrepo import RepoUnavailable
from .service import Conflict, Invalid, Locked, NotFound, Registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("alice-source-registry")

MONITOR_INTERVAL_SECONDS = 5
TICK_STALE_SECONDS = 120
HASH_PATTERN = r"^[A-Za-z0-9:_\-]{8,128}$"
ID_PATTERN = r"^[a-z0-9]{12}$"
STAGE_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"


async def _monitor(reg: Registry) -> None:
    while True:
        try:
            await reg.tick()
        except Exception:
            logger.exception("monitor tick failed")
        await asyncio.sleep(MONITOR_INTERVAL_SECONDS)


def _redis_client(settings: Settings):
    if not settings.redis_host:
        logger.warning("REDIS_HOST not set: work queue served from the register only")
        return None
    import redis.asyncio as aioredis

    return aioredis.Redis(host=settings.redis_host, port=settings.redis_port,
                          password=settings.redis_password or None, socket_timeout=5, socket_connect_timeout=5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    if not settings.postgres_dsn:
        raise RuntimeError("POSTGRES_DSN is not set")
    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=10)
    redis_client = _redis_client(settings)
    reg = Registry(settings, pool, redis_client)
    await reg.startup()  # RepoForeign aborts the start (AK-3)
    app.state.reg = reg
    monitor = asyncio.create_task(_monitor(reg))
    try:
        yield
    finally:
        monitor.cancel()
        try:
            if reg.available:
                await reg.flush_due(force=True)
        except Exception as exc:
            logger.warning("final batch flush failed: %s", exc)
        if redis_client is not None:
            await redis_client.aclose()
        await pool.close()


app = FastAPI(title="alice-source-registry", version="1.0.0", lifespan=lifespan)


def _reg(request: Request) -> Registry:
    return request.app.state.reg


# ---------------------------------------------------------------- errors
def _error(status: int, code: str, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": str(exc)})


@app.exception_handler(NotFound)
async def _not_found(_, exc):
    return _error(404, "not_found", exc)


@app.exception_handler(Locked)
async def _locked(_, exc):
    return _error(409, "locked", exc)


@app.exception_handler(Conflict)
async def _conflict(_, exc):
    return _error(409, "conflict", exc)


@app.exception_handler(Invalid)
async def _invalid(_, exc):
    return _error(422, "invalid", exc)


@app.exception_handler(RepoUnavailable)
async def _unavailable(_, exc):
    # Not a failed attempt: workers release their work and try again later (AK-30).
    return _error(503, "repo_unavailable", exc)


@app.exception_handler(md.InvalidDocument)
async def _invalid_doc(_, exc):
    return _error(409, "invalid_document", exc)


# ---------------------------------------------------------------- models
class Location(BaseModel):
    path: str | None = Field(None, min_length=1, max_length=4096)
    mailbox: str | None = Field(None, min_length=1, max_length=255)
    message_id: str | None = Field(None, min_length=1, max_length=998)

    @model_validator(mode="after")
    def _one_kind(self):
        if bool(self.path) == bool(self.mailbox and self.message_id) or (self.mailbox is None) != (self.message_id is None):
            raise ValueError("Fundort ist entweder 'path' oder 'mailbox' + 'message_id'")
        return self

    def as_dict(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class RegisterIn(BaseModel):
    kind: str
    hash: str = Field(..., pattern=HASH_PATTERN)
    title: str = Field(..., min_length=1, max_length=1000)
    location: Location
    size: int | None = Field(None, ge=0)
    modified: datetime | None = None
    captured: datetime | None = None
    parents: list[str] = Field(default_factory=list, max_length=100)
    stage: str = Field("detect", pattern=STAGE_PATTERN)
    batch: bool = False
    complete: bool = False  # mark `stage` done for a new source (detection, PROJ-116)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in md.KINDS:
            raise ValueError(f"kind muss einer von {', '.join(md.KINDS)} sein")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        if not v.strip():
            raise ValueError("title darf nicht leer sein")
        return v.strip()

    @field_validator("parents")
    @classmethod
    def _parents(cls, v):
        import re

        if any(not re.match(ID_PATTERN, p) for p in v):
            raise ValueError("parents enthält ungültige IDs")
        return v


class DocumentIn(BaseModel):
    stage: str = Field(..., pattern=STAGE_PATTERN)
    fields: dict = Field(default_factory=dict)
    content: str | None = Field(None, max_length=5_000_000)
    batch: bool = False


class OriginalIn(BaseModel):
    hash: str = Field(..., pattern=HASH_PATTERN)
    size: int | None = Field(None, ge=0)
    modified: datetime | None = None
    stage: str = Field("detect", pattern=STAGE_PATTERN)


class StageIn(BaseModel):
    name: str = Field(..., pattern=STAGE_PATTERN)
    position: int = Field(100, ge=0, le=100000)
    skip_kinds: list[str] = Field(default_factory=list)
    resets_on_content_change: bool = False

    @field_validator("skip_kinds")
    @classmethod
    def _kinds(cls, v):
        if any(k not in md.KINDS for k in v):
            raise ValueError(f"skip_kinds nur aus {', '.join(md.KINDS)}")
        return v


class ClaimIn(BaseModel):
    limit: int = Field(1, ge=1, le=100)


class TokenIn(BaseModel):
    token: uuid.UUID


class FailIn(TokenIn):
    error: str = Field(..., min_length=1, max_length=20000)


# ---------------------------------------------------------------- routes
@app.get("/health")
async def health(request: Request):
    reg = _reg(request)
    reasons = []
    try:
        await reg.pool.fetchval("SELECT 1")
    except Exception as exc:
        reasons.append(f"Datenbank nicht erreichbar: {exc}")
    if not reg.available:
        reasons.append(reg.unavailable_reason)
    if time.monotonic() - reg.last_tick > TICK_STALE_SECONDS:
        reasons.append("Hintergrund-Überwachung läuft nicht")
    body = {"status": "unhealthy" if reasons else "healthy", "repo": reg.available, "reasons": reasons,
            "batched": {s: len(b["ids"]) for s, b in reg.batches.items()}}
    return JSONResponse(status_code=503 if reasons else 200, content=body)


@app.post("/sources")
async def register(body: RegisterIn, request: Request):
    return await _reg(request).register(
        kind=body.kind, hash=body.hash, title=body.title, location=body.location.as_dict(), size=body.size,
        modified=body.modified, captured=body.captured, parents=body.parents, stage=body.stage, batch=body.batch,
        complete=body.complete)


@app.get("/sources")
async def by_hash(request: Request, hash: str = Query(..., pattern=HASH_PATTERN)):
    return await _reg(request).find_by_hash(hash)


@app.get("/sources/{source_id}")
async def get_source(source_id: str, request: Request):
    return await _reg(request).get_source(source_id)


@app.get("/sources/{source_id}/document")
async def read_document(source_id: str, request: Request):
    return await _reg(request).read_document(source_id)


@app.put("/sources/{source_id}/document")
async def write_document(source_id: str, body: DocumentIn, request: Request):
    return await _reg(request).write_document(source_id, stage=body.stage, fields=body.fields,
                                              content=body.content, batch=body.batch)


@app.post("/sources/{source_id}/locations")
async def add_location(source_id: str, body: Location, request: Request):
    return await _reg(request).add_location(source_id, body.as_dict())


@app.post("/sources/{source_id}/locations/gone")
async def remove_location(source_id: str, body: Location, request: Request):
    return await _reg(request).remove_location(source_id, body.as_dict())


@app.put("/sources/{source_id}/original")
async def update_original(source_id: str, body: OriginalIn, request: Request):
    return await _reg(request).update_original(source_id, hash=body.hash, size=body.size,
                                               modified=body.modified, stage=body.stage)


@app.get("/stages")
async def list_stages(request: Request):
    return {"stages": await _reg(request).list_stages()}


@app.post("/stages")
async def add_stage(body: StageIn, request: Request):
    return await _reg(request).add_stage(name=body.name, position=body.position, skip_kinds=body.skip_kinds,
                                         resets_on_content_change=body.resets_on_content_change)


@app.post("/stages/{stage}/claim")
async def claim(stage: str, request: Request, body: ClaimIn | None = None):
    return await _reg(request).claim(stage, (body or ClaimIn()).limit)


@app.post("/sources/{source_id}/stages/{stage}/done")
async def done(source_id: str, stage: str, body: TokenIn, request: Request):
    return await _reg(request).complete(source_id, stage, str(body.token))


@app.post("/sources/{source_id}/stages/{stage}/fail")
async def fail(source_id: str, stage: str, body: FailIn, request: Request):
    return await _reg(request).fail(source_id, stage, str(body.token), body.error)


@app.post("/sources/{source_id}/stages/{stage}/release")
async def release(source_id: str, stage: str, body: TokenIn, request: Request):
    return await _reg(request).release(source_id, stage, str(body.token))


@app.post("/sources/{source_id}/stages/{stage}/retry")
async def retry(source_id: str, stage: str, request: Request):
    return await _reg(request).retry(source_id, stage)


@app.post("/maintenance/scan")
async def scan(request: Request):
    return await _reg(request).scan()


@app.post("/maintenance/flush")
async def flush(request: Request):
    reg = _reg(request)
    reg.require_available()
    return {"flushed": await reg.flush_due(force=True)}


@app.post("/maintenance/resync-queue")
async def resync(request: Request):
    return {"rebuilt": await _reg(request).resync_queue()}
