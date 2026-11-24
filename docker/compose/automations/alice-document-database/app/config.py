"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    registry_url: str = "http://alice-source-registry:8012"
    registry_timeout_seconds: float = 120
    postgres_dsn: str = ""
    concurrency: int = 2
    poll_seconds: float = 10
    heartbeat_seconds: float = 60
    db_retry_seconds: float = 30
    registry_grace_seconds: float = 60

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
            concurrency=max(1, num("DATABASE_CONCURRENCY", d.concurrency, int)),
            poll_seconds=num("DATABASE_POLL_SECONDS", d.poll_seconds),
            heartbeat_seconds=num("DATABASE_HEARTBEAT_SECONDS", d.heartbeat_seconds),
            db_retry_seconds=num("DATABASE_DB_RETRY_SECONDS", d.db_retry_seconds),
            registry_grace_seconds=num("DATABASE_REGISTRY_GRACE_SECONDS", d.registry_grace_seconds),
        )
