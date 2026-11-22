"""
alice-text-extraction — stage `extract` of the new ETL (PROJ-117).

Takes due work of kind `document` from the source register (alice-source-registry,
PROJ-115), reads the original from the NAS (read only), turns it into Markdown with
page / slide / sheet sections and writes it through the register into the source
markdown. No LLM, no Redis, no MQTT, no database of its own.

Internal HTTP interface, only reachable inside the Docker network: there is
deliberately no nginx route.

Endpoints:
  GET /health   healthy / warning (paused) / unhealthy (register unreachable, loop stopped)
  GET /status   sources currently in work, counters since start
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
from .extractor import Extractor
from .registry import RegistryClient
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("alice-text-extraction")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    registry = RegistryClient(settings.registry_url, settings.registry_timeout_seconds)
    worker = Worker(settings, registry, Extractor(settings))
    app.state.worker = worker
    logger.info("Text extraction started (concurrency %d, register %s)", settings.concurrency, settings.registry_url)
    loop = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        loop.cancel()
        # unfinished work is not written; the register takes it back after its timeout (AK-34)
        await worker.stop()
        await registry.close()


app = FastAPI(title="alice-text-extraction", version="1.0.0", lifespan=lifespan)


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
    active = [{"source_id": sid, "title": a.get("title"), "progress": a.get("progress"),
               "since": datetime.fromtimestamp(a["started"], timezone.utc).isoformat(),
               "seconds": round(now - a["started"])} for sid, a in worker.active.items()]
    return {"concurrency": worker.s.concurrency, "active": active, "counts": worker.stats}
