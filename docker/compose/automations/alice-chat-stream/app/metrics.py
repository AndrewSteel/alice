"""Prometheus metrics for alice-chat-stream."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

CHAT_REQUESTS_TOTAL = Counter(
    "chat_requests_total",
    "Total /stream/chat requests",
    ["path"],  # HA_FAST | LLM_ONLY | error
)

CHAT_TOKENS_TOTAL = Counter(
    "chat_tokens_total",
    "Total tokens streamed to clients",
)

CHAT_LATENCY_SECONDS = Histogram(
    "chat_latency_seconds",
    "Wall-clock time from request received to stream done",
    ["path"],
    buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0),
)

TOOL_CALLS_TOTAL = Counter(
    "chat_tool_calls_total",
    "Tool invocations during streaming",
    ["tool", "outcome"],  # outcome: success | error | timeout
)
