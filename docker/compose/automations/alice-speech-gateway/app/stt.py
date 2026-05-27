"""
Speech-to-text engine — faster-whisper large-v3 on the TITAN X GPU.

The faster-whisper model is loaded once at startup and shared across all
concurrent sessions (one VRAM copy). Transcription is CPU/GPU-bound, so it
runs in a thread pool to avoid blocking the asyncio event loop.

`STTEngine` is the abstract interface; `WhisperEngine` is the real
implementation. Tests inject a fake engine that returns canned transcripts
so they run without a GPU.
"""
from __future__ import annotations

import asyncio
import io
import logging
from abc import ABC, abstractmethod

from . import config

logger = logging.getLogger("alice-speech-gateway.stt")


class STTEngine(ABC):
    """Abstract STT engine. Implementations transcribe raw audio bytes."""

    @abstractmethod
    async def transcribe(self, audio: bytes, language: str | None = None) -> str:
        """Transcribe a complete audio clip; return the (possibly empty) text."""

    async def warmup(self) -> None:  # noqa: B027 — optional override
        """Optionally pre-load the model. Default: no-op."""


class WhisperEngine(STTEngine):
    """faster-whisper implementation. Loads the model lazily on first use."""

    def __init__(self) -> None:
        self._model = None
        self._load_lock = asyncio.Lock()

    async def _ensure_model(self):
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is not None:
                return self._model
            # Import here so test environments without faster-whisper / CUDA
            # can still import this module.
            from faster_whisper import WhisperModel

            def _load():
                logger.info(
                    "Loading faster-whisper model=%s device=%s compute=%s",
                    config.WHISPER_MODEL,
                    config.WHISPER_DEVICE,
                    config.WHISPER_COMPUTE_TYPE,
                )
                return WhisperModel(
                    config.WHISPER_MODEL,
                    device=config.WHISPER_DEVICE,
                    compute_type=config.WHISPER_COMPUTE_TYPE,
                    download_root=config.WHISPER_MODEL_DIR,
                    local_files_only=True,
                )

            self._model = await asyncio.to_thread(_load)
            logger.info("faster-whisper model ready")
        return self._model

    async def warmup(self) -> None:
        await self._ensure_model()

    async def transcribe(self, audio: bytes, language: str | None = None) -> str:
        model = await self._ensure_model()
        lang = language or config.SPEECH_LANGUAGE

        def _run() -> str:
            # faster-whisper accepts a file-like object; ffmpeg-decodable
            # containers (wav/webm/ogg) are handled internally.
            segments, _info = model.transcribe(
                io.BytesIO(audio),
                language=lang,
                vad_filter=True,
            )
            return " ".join(seg.text.strip() for seg in segments).strip()

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:  # noqa: BLE001 — surface as STT failure
            logger.error("Whisper transcription failed: %s", exc)
            raise STTError("Spracherkennung fehlgeschlagen") from exc


class STTError(Exception):
    """Raised when transcription fails (decoding error, model error)."""


# Module-level singleton — set at app startup, swappable in tests.
_engine: STTEngine = WhisperEngine()


def get_engine() -> STTEngine:
    return _engine


def set_engine(engine: STTEngine) -> None:
    """Replace the active engine — used by tests to inject a fake."""
    global _engine
    _engine = engine
