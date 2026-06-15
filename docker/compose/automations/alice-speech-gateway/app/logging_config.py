"""Structured JSON logging — same shape as alice-chat-stream."""
from __future__ import annotations

import json
import logging
import re

from . import config

_TOKEN_PAT = re.compile(r"(?<=[?&])token=[^\s\"'&]+")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k in ("session_id", "user_id", "mode", "client_ip", "latency_ms"):
            v = getattr(record, k, None)
            if v is not None:
                payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _TokenRedactFilter(logging.Filter):
    """Redact ?token=<jwt> from log args before the message is formatted.

    uvicorn 0.49 logs 'WebSocket /ws/voice?token=<JWT> [accepted]' via the
    uvicorn.error logger (propagate=False, own handler) — not through our JSON
    handler. A filter on the logger itself catches all handlers at once.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(
                _TOKEN_PAT.sub("token=<redacted>", a) if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        record.msg = _TOKEN_PAT.sub("token=<redacted>", str(record.msg))
        return True


def setup_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.setLevel(config.LOG_LEVEL)
    # uvicorn.error is used by WebSocketProtocol (propagate=False, own handler),
    # so --no-access-log doesn't suppress WS lifecycle lines. The filter redacts
    # ?token= from any message that passes through this logger.
    logging.getLogger("uvicorn.error").addFilter(_TokenRedactFilter())
