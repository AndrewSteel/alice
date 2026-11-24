"""
alice-document-database — stage `database` of the new ETL (PROJ-119).

Takes due work of kind `document` whose classification is done from the source register
(alice-source-registry, PROJ-115), reads the frontmatter of the source markdown through the register
and replaces the rows of the document in the tables alice.doc_* in one transaction: document row,
detail row per type, bookings, invoice line items. Deleted sources are removed. Possible duplicate
bookings across bank statements of the same IBAN are marked. No LLM, no Redis, no Weaviate, no MQTT;
never writes the markdown.

Internal HTTP interface, only reachable inside the Docker network: there is deliberately no
nginx route.

Endpoints:
  GET /health   healthy / warning (paused) / unhealthy (register unreachable, loop stopped)
  GET /status   documents currently in work, counters since start
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .registry import RegistryClient
from .store import Store
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("alice-document-database")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    if not settings.postgres_dsn:
        raise RuntimeError("POSTGRES_DSN is not set")
    registry = RegistryClient(settings.registry_url, settings.registry_timeout_seconds)
    store = Store(settings.postgres_dsn)
    worker = Worker(settings, registry, store)
    app.state.worker = worker
    logger.info("Database stage started (concurrency %d, register %s)", settings.concurrency, settings.registry_url)
    loop = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        loop.cancel()
        # unfinished transactions are rolled back; the register takes the work back after its timeout
        await worker.stop()
        await registry.close()
        await store.close()


app = FastAPI(title="alice-document-database", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health(request: Request):
    worker: Worker = request.app.state.worker
    errors, warnings = worker.health()
    status = "unhealthy" if errors else ("warning" if warnings else "healthy")
    return JSONResponse(status_code=503 if errors else 200,
                        content={"status": status, "active": len(worker.active), "errors": errors,
                                 "warnings": warnings})


@app.get("/status")
async def status(request: Request):
    worker: Worker = request.app.state.worker
    now = time.time()
    active = [{"source_id": a["source_id"], "title": a.get("title"), "progress": a.get("progress"),
               "since": datetime.fromtimestamp(a["started"], timezone.utc).isoformat(),
               "seconds": round(now - a["started"])} for a in worker.active.values()]
    return {"concurrency": worker.s.concurrency, "active": active, "counts": worker.stats}
