"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time as dtime
from zoneinfo import ZoneInfo

MIN_RETENTION_DAYS = 30


def parse_limits(value: str) -> dict[str, int]:
    """"classify=10,extract=20" → {"classify": 10, "extract": 20}."""
    out: dict[str, int] = {}
    for part in value.split(","):
        if "=" in part:
            name, n = part.split("=", 1)
            out[name.strip()] = max(1, int(n))
    return out


@dataclass
class Settings:
    postgres_dsn: str = ""
    registry_url: str = "http://alice-source-registry:8012"
    detection_url: str = "http://alice-file-detection:8013"
    mail_import_url: str = "http://alice-mail-import:8019"  # PROJ-123, empty = levels 5/6 off
    stage_limit: int = 50
    stage_limits: dict[str, int] = field(default_factory=dict)
    log_interval_seconds: float = 900
    tick_seconds: float = 2
    nightly_time: str = "03:00"
    timezone: str = "Europe/Berlin"
    catchup_hours: float = 6
    pending_limit_hours: float = 24
    repair_limit_percent: float = 5
    hash_cycle_days: float = 30
    hash_portion_seconds: float = 3600
    hash_portion_bytes: int | None = None
    retention_days: int = 90
    http_timeout_seconds: float = 120
    long_timeout_seconds: float = 6 * 3600  # level 1 listing and re-hash run long on a big NAS

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def nightly(self) -> dtime:
        hh, mm = self.nightly_time.split(":")
        return dtime(int(hh), int(mm))

    @property
    def keep_days(self) -> int:
        return max(MIN_RETENTION_DAYS, self.retention_days)

    def limit(self, stage: str) -> int:
        return self.stage_limits.get(stage, self.stage_limit)

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        s = cls(
            postgres_dsn=env.get("POSTGRES_DSN", ""),
            registry_url=(env.get("REGISTRY_URL") or "http://alice-source-registry:8012").rstrip("/"),
            detection_url=(env.get("DETECTION_URL") or "http://alice-file-detection:8013").rstrip("/"),
            mail_import_url=(env.get("MAIL_IMPORT_URL", "http://alice-mail-import:8019") or "").rstrip("/"),
            stage_limit=max(1, int(env.get("REBUILD_STAGE_LIMIT") or 50)),
            stage_limits=parse_limits(env.get("REBUILD_STAGE_LIMITS") or ""),
            log_interval_seconds=float(env.get("REBUILD_LOG_INTERVAL_SECONDS") or 900),
            nightly_time=env.get("RECONCILE_NIGHTLY_TIME") or "03:00",
            timezone=env.get("RECONCILE_TIMEZONE") or "Europe/Berlin",
            catchup_hours=float(env.get("RECONCILE_CATCHUP_HOURS") or 6),
            pending_limit_hours=float(env.get("RECONCILE_PENDING_LIMIT_HOURS") or 24),
            repair_limit_percent=float(env.get("RECONCILE_REPAIR_LIMIT_PERCENT") or 5),
            hash_cycle_days=float(env.get("RECONCILE_HASH_CYCLE_DAYS") or 30),
            hash_portion_seconds=float(env.get("RECONCILE_HASH_PORTION_SECONDS") or 3600),
            hash_portion_bytes=int(env["RECONCILE_HASH_PORTION_BYTES"]) if env.get("RECONCILE_HASH_PORTION_BYTES") else None,
            retention_days=int(env.get("RECONCILE_RETENTION_DAYS") or 90),
        )
        s.nightly  # validate early: "HH:MM"
        return s
