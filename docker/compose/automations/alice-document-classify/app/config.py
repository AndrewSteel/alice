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
    gateway_url: str = "http://alice-llm-gateway:8011"
    gateway_key: str = ""
    model: str = ""
    concurrency: int = 1
    poll_seconds: float = 10
    heartbeat_seconds: float = 60
    llm_timeout_seconds: float = 900
    llm_retry_seconds: float = 60
    max_tokens: int = 8192
    confidence_threshold: float = 0.7
    retry_temperature: float = 0.7
    head_chars: int = 20000
    chunk_chars: int = 8000
    language_threshold: float = 0.15
    timezone: str = "Europe/Berlin"
    registry_grace_seconds: float = 60
    batch: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        d = cls()

        def num(name, default, typ=float):
            raw = env.get(name)
            return typ(raw) if raw not in (None, "") else default

        return cls(
            registry_url=(env.get("REGISTRY_URL") or d.registry_url).rstrip("/"),
            gateway_url=(env.get("LLM_GATEWAY_URL") or d.gateway_url).rstrip("/"),
            gateway_key=env.get("LLM_GATEWAY_KEY") or "",
            model=env.get("CLASSIFY_MODEL") or "",
            concurrency=max(1, num("CLASSIFY_CONCURRENCY", d.concurrency, int)),
            poll_seconds=num("CLASSIFY_POLL_SECONDS", d.poll_seconds),
            heartbeat_seconds=num("CLASSIFY_HEARTBEAT_SECONDS", d.heartbeat_seconds),
            llm_timeout_seconds=num("CLASSIFY_LLM_TIMEOUT_SECONDS", d.llm_timeout_seconds),
            llm_retry_seconds=num("CLASSIFY_LLM_RETRY_SECONDS", d.llm_retry_seconds),
            max_tokens=num("CLASSIFY_MAX_TOKENS", d.max_tokens, int),
            confidence_threshold=num("CLASSIFY_CONFIDENCE_THRESHOLD", d.confidence_threshold),
            retry_temperature=num("CLASSIFY_RETRY_TEMPERATURE", d.retry_temperature),
            head_chars=max(1000, num("CLASSIFY_HEAD_CHARS", d.head_chars, int)),
            chunk_chars=max(1000, num("CLASSIFY_CHUNK_CHARS", d.chunk_chars, int)),
            language_threshold=num("CLASSIFY_LANGUAGE_THRESHOLD", d.language_threshold),
            timezone=env.get("CLASSIFY_TIMEZONE") or d.timezone,
            registry_grace_seconds=num("CLASSIFY_REGISTRY_GRACE_SECONDS", d.registry_grace_seconds),
            batch=_bool(env.get("CLASSIFY_BATCH")),
        )
