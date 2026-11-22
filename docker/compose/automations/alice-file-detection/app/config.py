"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time as dtime
from zoneinfo import ZoneInfo

DEFAULT_EXTENSIONS = {
    "document": "pdf,txt,md,docx,doc,xlsx,xls,odt,ods",
    "image": "jpg,jpeg,png,webp,heic,tif,tiff",
    "audio": "mp3,m4a,wav,flac,ogg,aac",
    "video": "mp4,mov,mkv,avi,m4v,webm",
}
DEFAULT_SKIP_DIRS = "@eaDir,#recycle"
DEFAULT_SKIP_FILES = "~$*,*.tmp,*.part,*.crdownload,Thumbs.db,desktop.ini"
MIN_RETENTION_DAYS = 30


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def extension_map(spec: dict[str, str]) -> dict[str, str]:
    """{kind: "pdf,txt"} → {"pdf": "document", ...} (lower case, without dot)."""
    out: dict[str, str] = {}
    for kind, exts in spec.items():
        for ext in _list(exts):
            out[ext.lower().lstrip(".")] = kind
    return out


@dataclass
class Settings:
    postgres_dsn: str = ""
    registry_url: str = "http://alice-source-registry:8012"
    scan_interval_seconds: int = 300
    nightly_time: str = "02:00"
    timezone: str = "Europe/Berlin"
    catchup_hours: float = 6
    delete_limit_percent: float = 20
    nas_root: str = "/mnt/nas"
    extensions: dict[str, str] = field(default_factory=lambda: extension_map(DEFAULT_EXTENSIONS))
    skip_dirs: list[str] = field(default_factory=lambda: _list(DEFAULT_SKIP_DIRS))
    skip_files: list[str] = field(default_factory=lambda: _list(DEFAULT_SKIP_FILES))
    exclude_paths: list[str] = field(default_factory=list)
    summary_retention_days: int = 90
    registry_timeout_seconds: float = 120

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def nightly(self) -> dtime:
        hh, mm = self.nightly_time.split(":")
        return dtime(int(hh), int(mm))

    @property
    def retention_days(self) -> int:
        return max(MIN_RETENTION_DAYS, self.summary_retention_days)

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        exts = {k: env.get(f"DETECT_EXT_{k.upper()}") or v for k, v in DEFAULT_EXTENSIONS.items()}
        s = cls(
            postgres_dsn=env.get("POSTGRES_DSN", ""),
            registry_url=(env.get("REGISTRY_URL") or "http://alice-source-registry:8012").rstrip("/"),
            scan_interval_seconds=int(env.get("DETECT_SCAN_INTERVAL_SECONDS") or 300),
            nightly_time=env.get("DETECT_NIGHTLY_TIME") or "02:00",
            timezone=env.get("DETECT_TIMEZONE") or "Europe/Berlin",
            catchup_hours=float(env.get("DETECT_CATCHUP_HOURS") or 6),
            delete_limit_percent=float(env.get("DETECT_DELETE_LIMIT_PERCENT") or 20),
            nas_root=(env.get("DETECT_NAS_ROOT") or "/mnt/nas").rstrip("/") or "/",
            extensions=extension_map(exts),
            skip_dirs=_list(env.get("DETECT_SKIP_DIRS") or DEFAULT_SKIP_DIRS),
            skip_files=_list(env.get("DETECT_SKIP_FILES") or DEFAULT_SKIP_FILES),
            exclude_paths=[p.rstrip("/") for p in _list(env.get("DETECT_EXCLUDE_PATHS") or "")],
            summary_retention_days=int(env.get("DETECT_SUMMARY_RETENTION_DAYS") or 90),
        )
        s.nightly  # validate early: "HH:MM"
        return s
