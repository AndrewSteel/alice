"""
alice-speech-gateway — speech I/O service for the Alice assistant (PROJ-40).

Hosts three transports:
  - Wyoming TCP server on port 10300  — HA Voice Devices (replaces wyoming-whisper)
  - WebSocket /ws/stt  on port 10301  — WebApp transcription-only
  - WebSocket /ws/voice on port 10301 — WebApp full voice conversation

The faster-whisper model is loaded once at startup and shared across all
concurrent sessions. The Wyoming server runs as a background asyncio task
alongside the uvicorn HTTP/WebSocket server.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from wyoming.info import AsrModel, AsrProgram, Attribution, Info

from . import config, service_token
from .logging_config import setup_logging
from .stt import WhisperEngine, get_engine, set_engine
from .ws_transport import router as ws_router
from .wyoming_transport import run_wyoming_server

setup_logging()
logger = logging.getLogger("alice-speech-gateway")

# Background Wyoming server task — held so it can be cancelled on shutdown.
_wyoming_task: asyncio.Task | None = None


def _build_wyoming_info() -> Info:
    """Wyoming ASR program description advertised to HA Voice Devices."""
    return Info(
        asr=[
            AsrProgram(
                name="alice-speech-gateway",
                description="Alice speech gateway (faster-whisper + full voice pipeline)",
                attribution=Attribution(name="Alice", url="https://github.com/"),
                installed=True,
                version="1.0.0",
                models=[
                    AsrModel(
                        name=config.WHISPER_MODEL,
                        description=f"faster-whisper {config.WHISPER_MODEL}",
                        attribution=Attribution(name="SYSTRAN", url="https://github.com/"),
                        installed=True,
                        version=None,
                        languages=[config.SPEECH_LANGUAGE],
                    )
                ],
            )
        ]
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _wyoming_task

    # Ensure a real engine is active (tests may have swapped in a fake).
    if not isinstance(get_engine(), WhisperEngine):
        logger.info("Non-default STT engine active — skipping model warmup")
    else:
        set_engine(WhisperEngine())
        try:
            await get_engine().warmup()
        except Exception as exc:  # noqa: BLE001 — log, keep serving
            logger.error("STT warmup failed (will retry on first request): %s", exc)

    # Start the Wyoming server only if a service token can be minted.
    if service_token.wyoming_enabled():
        device_mapping = config.load_device_mapping()
        info = _build_wyoming_info()
        _wyoming_task = asyncio.create_task(run_wyoming_server(device_mapping, info))
        logger.info("Wyoming endpoint enabled (port %d)", config.WYOMING_PORT)
    else:
        logger.warning(
            "Wyoming endpoint DISABLED — SERVICE_JWT_PRIVATE_KEY_PATH not configured. "
            "WebApp WS endpoints remain available."
        )

    try:
        yield
    finally:
        if _wyoming_task is not None:
            _wyoming_task.cancel()
            try:
                await _wyoming_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="alice-speech-gateway", version="1.0.0", lifespan=lifespan)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict:
    jwt_ok = bool(config.JWT_PUBLIC_KEY_PATH)
    wyoming_ok = service_token.wyoming_enabled()
    status = "ok" if jwt_ok else "degraded"
    return {
        "status": status,
        "jwt_public_key": jwt_ok,
        "wyoming_enabled": wyoming_ok,
        "whisper_model": config.WHISPER_MODEL,
    }
