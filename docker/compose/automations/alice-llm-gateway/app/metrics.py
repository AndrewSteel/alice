"""Prometheus metrics for alice-llm-gateway (PROJ-111)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

_WAIT_BUCKETS = (0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 300.0, 600.0)

QUEUE_LENGTH = Gauge(
    "llm_gateway_queue_length",
    "Requests currently waiting for the llama-3090 slot",
    ["tier"],  # interactive | background
)

SLOT_BUSY = Gauge(
    "llm_gateway_slot_busy",
    "1 while a request is being forwarded to llama-3090",
)

QUEUE_WAIT_SECONDS = Histogram(
    "llm_gateway_queue_wait_seconds",
    "Time a request waited in the queue before it got the slot",
    ["tier"],
    buckets=_WAIT_BUCKETS,
)

UPSTREAM_SECONDS = Histogram(
    "llm_gateway_upstream_seconds",
    "Time a request held the slot (forwarding to llama-3090 until response end)",
    ["tier"],
    buckets=_WAIT_BUCKETS,
)

REQUESTS_TOTAL = Counter(
    "llm_gateway_requests_total",
    "Authenticated requests by tier and outcome",
    ["tier", "outcome"],  # outcome: ok | error | timeout | client_abort
)

REJECTED_TOTAL = Counter(
    "llm_gateway_rejected_total",
    "Requests rejected before queueing",
    ["reason"],  # unauthorized | too_large
)
