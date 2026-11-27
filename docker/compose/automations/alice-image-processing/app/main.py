"""
alice-image-processing — images in the source of truth (PROJ-125).

Two work loops on the source register (alice-source-registry, PROJ-115), only for sources of kind
`image` (watched folders and mail attachments):
- stage `extract`: EXIF from the original, a German description, a short title and the text in the
  image by the vision model through alice-llm-gateway (background key, no thinking);
- stage `locate`: place from GPS, taken over from the old Weaviate collection `Image` (read only)
  or reverse geocoded at Geoapify (daily limit, max. calls per second).
New images before the backlog; the backlog description stays locked until IMAGE_BACKLOG_RELEASED.
Markdowns are written only through the register. No Redis, no MQTT.

Internal HTTP interface, only reachable inside the Docker network: there is deliberately no nginx route.

Endpoints:
  GET  /health                 healthy / warning (paused) / unhealthy (register or database unreachable)
  GET  /status                 images in work, counters, backlog boundary, Geoapify calls today
  POST /describe/{source_id}   describe exactly this image next (also from the locked backlog)
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .geo import Geoapify, OldWeaviate
from .registry import DESCRIBE, RegistryClient, RegistryConflict, RegistryNotFound, RegistryUnavailable
from .store import Store
from .vision import VisionClient
from .worker import Describer, Locator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("alice-image-processing")

ID = re.compile(r"^[a-z0-9]{12}$")


class LazyPool:
    """asyncpg pool created on first use, so the service starts (and reports) while PostgreSQL is away."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = None

    def acquire(self):
        return _Acquire(self)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()


class _Acquire:
    def __init__(self, lazy: LazyPool):
        self.lazy = lazy
        self.cm = None

    async def __aenter__(self):
        if self.lazy.pool is None:
            if not self.lazy.dsn:
                raise ConnectionError("POSTGRES_DSN nicht gesetzt")
            self.lazy.pool = await asyncpg.create_pool(dsn=self.lazy.dsn, min_size=1, max_size=4, timeout=10)
        self.cm = self.lazy.pool.acquire()
        return await self.cm.__aenter__()

    async def __aexit__(self, *exc):
        return await self.cm.__aexit__(*exc)


def build(settings: Settings, registry: RegistryClient, store, vision: VisionClient, weaviate, geoapify):
    describer = Describer(settings, registry, store, vision)
    locator = Locator(settings, registry, store, weaviate, geoapify, describer)
    return describer, locator


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = Settings.from_env()
    pool = LazyPool(s.postgres_dsn)
    registry = RegistryClient(s.registry_url, s.registry_timeout_seconds)
    vision = VisionClient(s.gateway_url, s.gateway_key, s.model, s.llm_timeout_seconds, s.max_tokens)
    weaviate = OldWeaviate(s.weaviate_url, s.weaviate_timeout_seconds) if s.location_takeover else None
    geoapify = Geoapify(s.geoapify_url, s.geoapify_key, s.geoapify_timeout_seconds, s.geoapify_rate)
    store = Store(pool)
    describer, locator = build(s, registry, store, vision, weaviate, geoapify)
    app.state.describer, app.state.locator, app.state.store, app.state.registry = describer, locator, store, registry
    logger.info("Image processing started (concurrency %d, backlog released: %s, location takeover: %s, "
                "Geoapify limit %d/day)", s.concurrency, s.backlog_released, s.location_takeover,
                s.geoapify_daily_limit)
    loops = [asyncio.create_task(describer.run()), asyncio.create_task(locator.run())]
    try:
        yield
    finally:
        for t in loops:
            t.cancel()
        await describer.stop()  # unfinished work is not written; the register takes it back
        await asyncio.gather(*loops, return_exceptions=True)
        for c in (registry, vision, geoapify, *([weaviate] if weaviate else [])):
            await c.close()
        await pool.close()


app = FastAPI(title="alice-image-processing", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None,
              openapi_url=None)


@app.get("/health")
async def health(request: Request):
    errors, warnings = [], []
    for w in (request.app.state.describer, request.app.state.locator):
        e, wa = w.health()
        errors += e
        warnings += wa
    errors, warnings = list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))
    status = "unhealthy" if errors else ("warning" if warnings else "healthy")
    return JSONResponse(status_code=503 if errors else 200,
                        content={"status": status, "active": len(request.app.state.describer.active),
                                 "errors": errors, "warnings": warnings})


@app.get("/status")
async def status(request: Request):
    d: Describer = request.app.state.describer
    loc: Locator = request.app.state.locator
    now = time.time()
    active = [{"source_id": sid, "title": a.get("title"), "progress": a.get("progress"),
               "since": datetime.fromtimestamp(a["started"], timezone.utc).isoformat(),
               "seconds": round(now - a["started"])} for sid, a in d.active.items()]
    try:
        calls = await request.app.state.store.geocode_calls(loc.today())
    except Exception:
        calls = None
    return {"concurrency": d.s.concurrency, "backlog_released": d.s.backlog_released,
            "backlog_before": d.cutoff.isoformat() if d.cutoff else None,
            "location_takeover": d.s.location_takeover, "active": active,
            "locating": loc.current["source_id"] if loc.current else None,
            "geoapify": {"calls_today": calls, "daily_limit": d.s.geoapify_daily_limit},
            "counts": {"describe": d.stats, "locate": loc.stats}}


@app.post("/describe/{source_id}")
async def describe(source_id: str, request: Request):
    """Trigger the description of exactly this image (sample, troubleshooting; AK-33)."""
    if not ID.match(source_id):
        return JSONResponse(status_code=400, content={"detail": "ungültige Quell-ID"})
    registry: RegistryClient = request.app.state.registry
    try:
        src = await registry.get_source(source_id)
        if src.get("kind") != "image":
            return JSONResponse(status_code=409, content={"detail": "Quelle ist kein Bild"})
        if src.get("deleted"):
            return JSONResponse(status_code=409, content={"detail": "Quelle ist gelöscht"})
        if ((src.get("stages") or {}).get(DESCRIBE) or {}).get("state") == "running":
            return JSONResponse(status_code=409, content={"detail": "Beschreibung läuft bereits"})
        await registry.retry(source_id, DESCRIBE)
        await request.app.state.store.request(source_id)
    except RegistryNotFound:
        return JSONResponse(status_code=404, content={"detail": "Quelle nicht gefunden"})
    except RegistryConflict as exc:
        return JSONResponse(status_code=409, content={"detail": f"Nicht möglich: {exc}"[:300]})
    except RegistryUnavailable as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    except (OSError, asyncpg.PostgresError) as exc:
        return JSONResponse(status_code=503, content={"detail": f"PostgreSQL nicht erreichbar ({exc.__class__.__name__})"})
    logger.info("Description of %s triggered", source_id)
    return {"id": source_id, "queued": True}
