"""
Service-token minting for the Wyoming path (Mode 3).

The Wyoming endpoint receives no client JWT — HA Voice Devices have no
Alice login. But alice-chat-stream still requires a valid RS256 token to
identify the user. The gateway therefore mints a short-lived service token
for the mapped user, signed with the same RSA key pair as alice-auth.

This requires the RSA *private* key. To keep the security boundary tight:
  - The private key is mounted read-only at SERVICE_JWT_PRIVATE_KEY_PATH.
  - It is used ONLY here, ONLY for device-mapped Wyoming users.
  - If the private key is not mounted, the Wyoming path is disabled at
    startup (the WebApp WS endpoints still work with client JWTs).

If you prefer not to mount the private key, the alternative is to add an
internal-trust header to alice-chat-stream — out of scope for PROJ-40.
"""
from __future__ import annotations

import logging
import os
import time

import jwt

logger = logging.getLogger("alice-speech-gateway.service_token")

SERVICE_JWT_PRIVATE_KEY_PATH = os.environ.get("SERVICE_JWT_PRIVATE_KEY_PATH", "")
SERVICE_JWT_TTL_SECONDS = int(os.environ.get("SERVICE_JWT_TTL_SECONDS", "120"))
JWT_ALGORITHM = "RS256"

_private_key: str | None = None


def wyoming_enabled() -> bool:
    """True if the private key is configured — required for the Wyoming path."""
    return bool(SERVICE_JWT_PRIVATE_KEY_PATH) and os.path.exists(
        SERVICE_JWT_PRIVATE_KEY_PATH
    )


def _load_private_key() -> str:
    global _private_key
    if _private_key is not None:
        return _private_key
    if not wyoming_enabled():
        raise RuntimeError("SERVICE_JWT_PRIVATE_KEY_PATH is not configured")
    with open(SERVICE_JWT_PRIVATE_KEY_PATH) as f:
        _private_key = f.read()
    return _private_key


def mint_service_token(user_id: str) -> str:
    """
    Mint a short-lived RS256 token for `user_id`.

    Token shape matches alice-auth so alice-chat-stream accepts it unchanged.
    """
    now = int(time.time())
    payload = {
        "user_id": user_id,
        "username": f"voice-device-{user_id}",
        "role": "user",
        "iat": now,
        "exp": now + SERVICE_JWT_TTL_SECONDS,
        "iss": "alice-speech-gateway",
    }
    return jwt.encode(payload, _load_private_key(), algorithm=JWT_ALGORITHM)
