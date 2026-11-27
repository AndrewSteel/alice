"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    registry_url: str = "http://alice-source-registry:8012"
    registry_timeout_seconds: float = 120
    postgres_dsn: str = ""
    gateway_url: str = "http://alice-llm-gateway:8011"
    gateway_key: str = ""
    model: str = ""
    weaviate_url: str = "http://weaviate:8080"
    geoapify_url: str = "https://api.geoapify.com"
    geoapify_key: str = ""
    concurrency: int = 1
    backlog_released: bool = False
    location_takeover: bool = True
    geoapify_daily_limit: int = 3000
    geoapify_rate: float = 5
    geoapify_timeout_seconds: float = 15
    weaviate_timeout_seconds: float = 15
    max_side_px: int = 1024
    max_megapixels: float = 250
    llm_timeout_seconds: float = 900
    llm_retry_seconds: float = 60
    max_tokens: int = 4096
    weaviate_retry_seconds: int = 300
    poll_seconds: float = 10
    heartbeat_seconds: float = 60
    nas_root: str = "/mnt/nas"
    missing_retry_seconds: int = 3600
    nas_retry_seconds: float = 60
    registry_grace_seconds: float = 60
    timezone: str = "Europe/Berlin"
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
            postgres_dsn=env.get("POSTGRES_DSN") or "",
            gateway_url=(env.get("LLM_GATEWAY_URL") or d.gateway_url).rstrip("/"),
            gateway_key=env.get("LLM_GATEWAY_KEY") or "",
            model=env.get("IMAGE_VISION_MODEL") or "",
            weaviate_url=(env.get("WEAVIATE_URL") or d.weaviate_url).rstrip("/"),
            geoapify_url=(env.get("GEOAPIFY_URL") or d.geoapify_url).rstrip("/"),
            geoapify_key=env.get("GEOAPIFY_API_KEY") or "",
            concurrency=max(1, num("IMAGE_DESCRIBE_CONCURRENCY", d.concurrency, int)),
            backlog_released=_bool(env.get("IMAGE_BACKLOG_RELEASED"), d.backlog_released),
            location_takeover=_bool(env.get("IMAGE_LOCATION_TAKEOVER"), d.location_takeover),
            geoapify_daily_limit=max(0, num("IMAGE_GEOAPIFY_DAILY_LIMIT", d.geoapify_daily_limit, int)),
            geoapify_rate=max(0.1, num("IMAGE_GEOAPIFY_RATE", d.geoapify_rate)),
            geoapify_timeout_seconds=num("IMAGE_GEOAPIFY_TIMEOUT_SECONDS", d.geoapify_timeout_seconds),
            weaviate_timeout_seconds=num("IMAGE_WEAVIATE_TIMEOUT_SECONDS", d.weaviate_timeout_seconds),
            max_side_px=max(64, num("IMAGE_MAX_SIDE_PX", d.max_side_px, int)),
            max_megapixels=num("IMAGE_MAX_MEGAPIXELS", d.max_megapixels),
            llm_timeout_seconds=num("IMAGE_LLM_TIMEOUT_SECONDS", d.llm_timeout_seconds),
            llm_retry_seconds=num("IMAGE_LLM_RETRY_SECONDS", d.llm_retry_seconds),
            max_tokens=num("IMAGE_MAX_TOKENS", d.max_tokens, int),
            weaviate_retry_seconds=num("IMAGE_WEAVIATE_RETRY_SECONDS", d.weaviate_retry_seconds, int),
            poll_seconds=num("IMAGE_POLL_SECONDS", d.poll_seconds),
            heartbeat_seconds=num("IMAGE_HEARTBEAT_SECONDS", d.heartbeat_seconds),
            nas_root=(env.get("IMAGE_NAS_ROOT") or d.nas_root).rstrip("/") or "/",
            missing_retry_seconds=num("IMAGE_MISSING_RETRY_SECONDS", d.missing_retry_seconds, int),
            nas_retry_seconds=num("IMAGE_NAS_RETRY_SECONDS", d.nas_retry_seconds),
            registry_grace_seconds=num("IMAGE_REGISTRY_GRACE_SECONDS", d.registry_grace_seconds),
            timezone=env.get("IMAGE_TIMEZONE") or d.timezone,
            batch=_bool(env.get("IMAGE_BATCH"), d.batch),
        )
