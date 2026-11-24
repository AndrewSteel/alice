"""
alice-document-classify — stage `classify` of the new ETL (PROJ-118).

Takes due work of kind `document` whose extraction is done from the source register
(alice-source-registry, PROJ-115), lets the local LLM determine the document type, extract the
fields of the type (all bookings of bank statements), a German title and a German summary, and
writes them through the register into the frontmatter of the source markdown. LLM calls only
through alice-llm-gateway as a background caller. No Redis, no Weaviate, no MQTT, no database of
its own.

Internal HTTP interface, only reachable inside the Docker network: there is deliberately no
nginx route.

Endpoints:
  GET /health   healthy / warning (paused) / unhealthy (register unreachable, key rejected, loop stopped)
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

from .classifier import Classifier
from .config import Settings
from .llm import LlmClient
from .registry import RegistryClient
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("alice-document-classify")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    registry = RegistryClient(settings.registry_url, settings.registry_timeout_seconds)
    llm = LlmClient(settings.gateway_url, settings.gateway_key, settings.model, settings.llm_timeout_seconds,
                    settings.max_tokens)
    worker = Worker(settings, registry, Classifier(settings, llm))
    app.state.worker = worker
    if not settings.gateway_key:
        logger.warning("LLM_GATEWAY_KEY is not set: the gateway will reject the calls")
    logger.info("Classification started (concurrency %d, register %s, gateway %s)", settings.concurrency,
                settings.registry_url, settings.gateway_url)
    loop = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        loop.cancel()
        # unfinished work is not written; the register takes it back after its timeout (AK-45)
        await worker.stop()
        await registry.close()
        await llm.close()


app = FastAPI(title="alice-document-classify", version="1.0.0", lifespan=lifespan)


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
