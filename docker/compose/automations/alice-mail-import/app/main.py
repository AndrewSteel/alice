"""
alice-mail-import — mail import into the ETL (PROJ-123).

IMAP mailboxes (alice.imap_mailboxes, read only: INBOX + sent) → mail archive on the NAS (`.eml` with
attachments stored next to it) → sources of kind `email` in alice-source-registry (stage detect),
stage extract (mail markdown) and stage classify (category + German summary through
alice-llm-gateway as background load), nightly reconciliation with the server and the levels 5/6 of
the completeness check of alice-etl-rebuild (PROJ-120).

Internal HTTP interface, only reachable inside the Docker network: there is deliberately no nginx
route and no end-user access (AK-54).

Endpoints:
  GET  /health                healthy / warning (paused) / unhealthy (database or loops down)
  GET  /status                mailboxes, counters, last nightly run
  POST /reconcile/check       levels 5 (IMAP <-> register) and 6 (register <-> mail archive), read only
  POST /reconcile/repair      import missing mails / store missing archive files again
  POST /maintenance/nightly   run the nightly reconciliation now
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .archive import Archive
from .config import Settings
from .importer import Importer, Paused
from .registry import RegistryClient
from .workers import ClassifyWorker, ExtractWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("alice-mail-import")

LOOP_STALE_SECONDS = 300


class Service:
    def __init__(self, settings: Settings, pool, registry: RegistryClient):
        self.s = settings
        self.pool = pool
        self.registry = registry
        self.importer = Importer(settings, pool, registry, Archive(settings.archive_path))
        self.extract = ExtractWorker(settings, registry, self.importer) if settings.extract_enabled else None
        self.classify = ClassifyWorker(settings, registry) if settings.classify_enabled else None
        self.tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self.tasks.append(asyncio.create_task(self.importer.run()))
        if self.extract:
            self.tasks.append(asyncio.create_task(self.extract.run()))
        if self.classify:
            self.tasks.append(asyncio.create_task(self.classify.run()))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.importer.stop()
        if self.classify:
            await self.classify.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    if not settings.postgres_dsn:
        raise RuntimeError("POSTGRES_DSN is not set")
    if not settings.mail_enc_key:
        logger.warning("MAIL_ENC_KEY is not set: mailbox passwords cannot be decrypted")
    if settings.classify_enabled and not settings.gateway_key:
        logger.warning("LLM_GATEWAY_KEY is not set: the gateway will reject the classify calls")
    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=10)
    registry = RegistryClient(settings.registry_url, settings.registry_timeout_seconds)
    svc = Service(settings, pool, registry)
    app.state.svc = svc
    svc.start()
    logger.info("Mail import started (archive %s, register %s)", settings.archive_path, settings.registry_url)
    try:
        yield
    finally:
        await svc.stop()
        await registry.close()
        await pool.close()


app = FastAPI(title="alice-mail-import", version="1.0.0", lifespan=lifespan)


def _svc(request: Request) -> Service:
    return request.app.state.svc


@app.get("/health")
async def health(request: Request):
    svc = _svc(request)
    errors, warnings = [], []
    try:
        await svc.pool.fetchval("SELECT 1")
    except Exception as exc:
        errors.append(f"Datenbank nicht erreichbar: {exc.__class__.__name__}")
    now = time.monotonic()
    loops = [("Import", svc.importer)] + [(n, w) for n, w in (("extract", svc.extract), ("classify", svc.classify)) if w]
    for name, loop in loops:
        if now - loop.last_tick > LOOP_STALE_SECONDS + getattr(loop, "poll", 0):
            errors.append(f"Schleife {name} läuft nicht")
    if svc.importer.paused_reason:
        warnings.append(f"Import pausiert: {svc.importer.paused_reason}")
    for name, w in (("extract", svc.extract), ("classify", svc.classify)):
        if w and w.paused_reason:
            warnings.append(f"Stufe {name} pausiert: {w.paused_reason}")
    if svc.classify and svc.classify.llm_paused_until > now:
        warnings.append(f"LLM nicht verfügbar: {svc.classify.llm_reason}")
    status = "unhealthy" if errors else ("warning" if warnings else "healthy")
    return JSONResponse(status_code=503 if errors else 200,
                        content={"status": status, "errors": errors, "warnings": warnings})


@app.get("/status")
async def status(request: Request):
    svc = _svc(request)
    async with svc.pool.acquire() as con:
        boxes = await con.fetch(
            "SELECT i.id, m.archive_key, i.status, i.last_synced_at, i.last_error, i.mails_indexed, i.next_sync_at "
            "FROM alice.imap_mailboxes i LEFT JOIN alice.mail_import_mailboxes m ON m.mailbox_id = i.id "
            "ORDER BY i.created_at, i.id LIMIT 100")
        run = await con.fetchrow("SELECT id, kind, state, started_at, finished_at, summary FROM alice.mail_import_runs "
                                 "ORDER BY started_at DESC, id DESC LIMIT 1")
    return {
        "mailboxes": [{k: (v.isoformat() if hasattr(v, "isoformat") else (str(v) if k == "id" else v))
                       for k, v in dict(b).items()} for b in boxes],
        "running": list(svc.importer.running),
        "import": svc.importer.stats,
        "extract": svc.extract.stats if svc.extract else None,
        "classify": svc.classify.stats if svc.classify else None,
        "last_nightly": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(run).items()} if run else None,
    }


class RepairItem(BaseModel):
    type: str = Field(..., pattern=r"^(mail_import|mail_rearchive)$")
    mailbox: str | None = Field(None, max_length=200)
    folder: str | None = Field(None, max_length=1000)
    uid: int | None = Field(None, ge=1)
    source_id: str | None = Field(None, pattern=r"^[a-z0-9]{12}$")
    gap: str | None = Field(None, max_length=40)
    path: str | None = Field(None, max_length=4096)


class RepairIn(BaseModel):
    items: list[RepairItem] = Field(..., min_length=1, max_length=10000)


@app.post("/reconcile/check")
async def reconcile_check(request: Request):
    try:
        return await _svc(request).importer.reconcile_check()
    except Paused as exc:
        return JSONResponse(status_code=503, content={"error": "unavailable", "detail": str(exc)})


@app.post("/reconcile/repair")
async def reconcile_repair(body: RepairIn, request: Request):
    for it in body.items:
        if it.type == "mail_import" and not (it.mailbox and it.folder and it.uid):
            return JSONResponse(status_code=422, content={"error": "invalid",
                                                          "detail": "mail_import braucht mailbox, folder, uid"})
        if it.type == "mail_rearchive" and not it.source_id:
            return JSONResponse(status_code=422, content={"error": "invalid",
                                                          "detail": "mail_rearchive braucht source_id"})
    try:
        results = await _svc(request).importer.reconcile_repair([i.model_dump() for i in body.items])
    except Paused as exc:
        return JSONResponse(status_code=503, content={"error": "unavailable", "detail": str(exc)})
    return {"results": results}


@app.post("/maintenance/nightly")
async def run_nightly(request: Request):
    return await _svc(request).importer.nightly("manual")
