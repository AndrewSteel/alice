"""Configuration for alice-llm-gateway (PROJ-111).

Callers authenticate with their own gateway key; the key alone decides the
caller name and tier. A request body/header can never raise the tier.

Clients file (one caller per line, `#` starts a comment):

    <name> <tier> <key>

`tier` is `interactive`; anything else (e.g. `background`) runs as background.
"""
from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass

from .scheduler import BACKGROUND, INTERACTIVE

logger = logging.getLogger("alice-llm-gateway.config")

UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "http://llama-3090:11434").rstrip("/")
UPSTREAM_KEY_FILE = os.environ.get("UPSTREAM_KEY_FILE", "/run/secrets/llama_api_key")
CLIENTS_FILE = os.environ.get("CLIENTS_FILE", "/run/secrets/llm_gateway_clients")
# Upper bound on silence from llama-3090 while a request holds the slot, so a
# hung upstream cannot block the queue forever. Queue wait is NOT limited —
# the callers' own timeouts stay authoritative.
UPSTREAM_READ_TIMEOUT = float(os.environ.get("UPSTREAM_READ_TIMEOUT_SECONDS", "900"))
UPSTREAM_CONNECT_TIMEOUT = float(os.environ.get("UPSTREAM_CONNECT_TIMEOUT_SECONDS", "10"))
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", str(50 * 1024 * 1024)))  # = nginx client_max_body_size


@dataclass(frozen=True)
class Client:
    name: str
    tier: str
    key: str


def parse_clients(text: str) -> list[Client]:
    clients: list[Client] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"clients file line {lineno}: expected '<name> <tier> <key>'")
        name, tier, key = parts
        if tier != INTERACTIVE:
            if tier != BACKGROUND:
                logger.warning("clients file line %d: unknown tier %r -> background", lineno, tier)
            tier = BACKGROUND
        clients.append(Client(name=name, tier=tier, key=key))
    if not clients:
        raise ValueError("clients file contains no callers")
    if len({c.key for c in clients}) != len(clients):
        raise ValueError("clients file contains duplicate keys")
    if len({c.name for c in clients}) != len(clients):
        raise ValueError("clients file contains duplicate names")
    return clients


def read_secret(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


def find_client(clients: list[Client], token: str) -> Client | None:
    """Constant-time lookup of the caller by its bearer token."""
    found = None
    for c in clients:
        if hmac.compare_digest(c.key.encode(), token.encode()):
            found = c
    return found
