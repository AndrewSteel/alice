"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    registry_url: str = "http://alice-source-registry:8012"
    registry_timeout_seconds: float = 120
    concurrency: int = 2
    poll_seconds: float = 10
    heartbeat_seconds: float = 60
    ocr_page_timeout_seconds: float = 120
    file_timeout_seconds: float = 600
    max_file_mb: float = 200
    language_min_chars: int = 100
    text_min_chars: int = 10
    text_min_quality: float = 0.6
    ocr_languages: str = "deu+eng"
    ocr_dpi: int = 300
    nas_root: str = "/mnt/nas"
    missing_retry_seconds: int = 3600
    nas_retry_seconds: float = 60
    registry_grace_seconds: float = 60
    batch: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        d = cls()

        def num(name, default, typ=float):
            raw = env.get(name)
            return typ(raw) if raw not in (None, "") else default

        s = cls(
            registry_url=(env.get("REGISTRY_URL") or d.registry_url).rstrip("/"),
            concurrency=max(1, num("EXTRACT_CONCURRENCY", d.concurrency, int)),
            poll_seconds=num("EXTRACT_POLL_SECONDS", d.poll_seconds),
            heartbeat_seconds=num("EXTRACT_HEARTBEAT_SECONDS", d.heartbeat_seconds),
            ocr_page_timeout_seconds=num("EXTRACT_OCR_PAGE_TIMEOUT_SECONDS", d.ocr_page_timeout_seconds),
            file_timeout_seconds=num("EXTRACT_FILE_TIMEOUT_SECONDS", d.file_timeout_seconds),
            max_file_mb=num("EXTRACT_MAX_FILE_MB", d.max_file_mb),
            language_min_chars=num("EXTRACT_LANGUAGE_MIN_CHARS", d.language_min_chars, int),
            text_min_chars=num("EXTRACT_TEXT_MIN_CHARS", d.text_min_chars, int),
            text_min_quality=num("EXTRACT_TEXT_MIN_QUALITY", d.text_min_quality),
            ocr_languages=env.get("EXTRACT_OCR_LANGUAGES") or d.ocr_languages,
            ocr_dpi=num("EXTRACT_OCR_DPI", d.ocr_dpi, int),
            nas_root=(env.get("EXTRACT_NAS_ROOT") or d.nas_root).rstrip("/") or "/",
            missing_retry_seconds=num("EXTRACT_MISSING_RETRY_SECONDS", d.missing_retry_seconds, int),
            nas_retry_seconds=num("EXTRACT_NAS_RETRY_SECONDS", d.nas_retry_seconds),
            registry_grace_seconds=num("EXTRACT_REGISTRY_GRACE_SECONDS", d.registry_grace_seconds),
            batch=_bool(env.get("EXTRACT_BATCH")),
        )
        return s
