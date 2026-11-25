"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    postgres_dsn: str = ""
    jwt_public_key_path: str = ""
    registry_url: str = "http://alice-source-registry:8012"
    rebuild_url: str = "http://alice-etl-rebuild:8017"
    retry_limit: int = 1000
    http_timeout_seconds: float = 30
    state_timeout_seconds: float = 3  # PROJ-120 calls of the 5-s refresh: fail fast, the page shows the banner
    retry_parallel: int = 10

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            postgres_dsn=env.get("POSTGRES_DSN", ""),
            jwt_public_key_path=env.get("JWT_PUBLIC_KEY_PATH", ""),
            registry_url=(env.get("REGISTRY_URL") or "http://alice-source-registry:8012").rstrip("/"),
            rebuild_url=(env.get("REBUILD_URL") or "http://alice-etl-rebuild:8017").rstrip("/"),
            retry_limit=max(1, int(env.get("ETL_RETRY_LIMIT") or 1000)),
        )
