"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time as dtime
from zoneinfo import ZoneInfo


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    postgres_dsn: str = ""
    registry_url: str = "http://alice-source-registry:8012"
    registry_timeout_seconds: float = 120
    mail_enc_key: str = ""
    archive_path: str = "/mnt/nas/ai/mail"
    sent_folder_fallback: str = "Sent"
    batch_size: int = 200
    batch_threshold: int = 20            # more new mails than this in one tick → batch commits
    history_pause_seconds: float = 5     # history left: mailbox due again after this pause
    delete_limit_percent: float = 20
    tick_seconds: float = 5
    imap_timeout_seconds: float = 120
    max_parallel_mailboxes: int = 4
    nightly_time: str = "02:30"
    catchup_hours: float = 6
    timezone: str = "Europe/Berlin"
    # stage extract
    extract_enabled: bool = True
    extract_poll_seconds: float = 5
    extract_batch_limit: int = 20
    # stage classify
    classify_enabled: bool = True
    gateway_url: str = "http://alice-llm-gateway:8011"
    gateway_key: str = ""
    model: str = ""
    classify_chars: int = 4000
    classify_poll_seconds: float = 10
    classify_heartbeat_seconds: float = 60
    llm_timeout_seconds: float = 900
    llm_retry_seconds: float = 60
    max_tokens: int = 1024

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def nightly(self) -> dtime:
        hh, mm = self.nightly_time.split(":")
        return dtime(int(hh), int(mm))

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        d = cls()

        def num(name, default, typ=float):
            raw = env.get(name)
            return typ(raw) if raw not in (None, "") else default

        s = cls(
            postgres_dsn=env.get("POSTGRES_DSN", ""),
            registry_url=(env.get("REGISTRY_URL") or d.registry_url).rstrip("/"),
            mail_enc_key=env.get("MAIL_ENC_KEY", ""),
            archive_path=(env.get("MAIL_ARCHIVE_PATH") or d.archive_path).rstrip("/") or "/",
            sent_folder_fallback=env.get("MAIL_SENT_FOLDER_FALLBACK") or d.sent_folder_fallback,
            batch_size=max(1, num("MAIL_BATCH_SIZE", d.batch_size, int)),
            batch_threshold=max(1, num("MAIL_BATCH_THRESHOLD", d.batch_threshold, int)),
            history_pause_seconds=num("MAIL_HISTORY_PAUSE_SECONDS", d.history_pause_seconds),
            delete_limit_percent=num("MAIL_DELETE_LIMIT_PERCENT", d.delete_limit_percent),
            tick_seconds=num("MAIL_TICK_SECONDS", d.tick_seconds),
            imap_timeout_seconds=num("MAIL_IMAP_TIMEOUT_SECONDS", d.imap_timeout_seconds),
            max_parallel_mailboxes=max(1, num("MAIL_MAX_PARALLEL_MAILBOXES", d.max_parallel_mailboxes, int)),
            nightly_time=env.get("MAIL_NIGHTLY_TIME") or d.nightly_time,
            catchup_hours=num("MAIL_NIGHTLY_CATCHUP_HOURS", d.catchup_hours),
            timezone=env.get("MAIL_TIMEZONE") or d.timezone,
            extract_enabled=not _bool(env.get("MAIL_EXTRACT_DISABLED")),
            extract_poll_seconds=num("MAIL_EXTRACT_POLL_SECONDS", d.extract_poll_seconds),
            classify_enabled=not _bool(env.get("MAIL_CLASSIFY_DISABLED")),
            gateway_url=(env.get("LLM_GATEWAY_URL") or d.gateway_url).rstrip("/"),
            gateway_key=env.get("LLM_GATEWAY_KEY", ""),
            model=env.get("CLASSIFY_MODEL", ""),
            classify_chars=max(200, num("MAIL_CLASSIFY_CHARS", d.classify_chars, int)),
            classify_poll_seconds=num("MAIL_CLASSIFY_POLL_SECONDS", d.classify_poll_seconds),
            llm_timeout_seconds=num("MAIL_LLM_TIMEOUT_SECONDS", d.llm_timeout_seconds),
            llm_retry_seconds=num("MAIL_LLM_RETRY_SECONDS", d.llm_retry_seconds),
            max_tokens=num("MAIL_CLASSIFY_MAX_TOKENS", d.max_tokens, int),
        )
        s.nightly  # validate early: "HH:MM"
        return s
