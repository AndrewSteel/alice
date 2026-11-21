"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass
class Settings:
    repo_path: str
    postgres_dsn: str = ""
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""
    stale_running_seconds: int = 1800
    scan_interval_seconds: int = 60
    git_lock_stale_seconds: int = 120
    batch_max_files: int = 500
    batch_max_seconds: int = 300
    timezone: str = "Europe/Berlin"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            repo_path=env.get("SOT_REPO_PATH", "/data/sot"),
            postgres_dsn=env.get("POSTGRES_DSN", ""),
            redis_host=env.get("REDIS_HOST", ""),
            redis_port=int(env.get("REDIS_PORT") or 6379),
            redis_password=env.get("REDIS_PASSWORD", ""),
            stale_running_seconds=int(env.get("SOT_STALE_RUNNING_SECONDS") or 1800),
            scan_interval_seconds=int(env.get("SOT_SCAN_INTERVAL_SECONDS") or 60),
            git_lock_stale_seconds=int(env.get("SOT_GIT_LOCK_STALE_SECONDS") or 120),
            batch_max_files=int(env.get("SOT_BATCH_MAX_FILES") or 500),
            batch_max_seconds=int(env.get("SOT_BATCH_MAX_SECONDS") or 300),
            timezone=env.get("SOT_TIMEZONE") or "Europe/Berlin",
        )
