"""
JWT verification (RS256, public key only) for alice-calendar.

Accepts both alice-auth tokens (WebApp) and alice-speech-gateway service
tokens (voice). The gateway mints its token for the identified speaker, or
for the nil UUID when the speaker was not recognised — that case is rejected
for every calendar action (spec: no fallback to admin or a device default).

The raw token is kept so it can be forwarded to alice-google-connect, whose
token endpoint is deliberately scoped to the calling user.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException

logger = logging.getLogger("alice-calendar.auth")

JWT_PUBLIC_KEY_PATH = os.environ.get("JWT_PUBLIC_KEY_PATH", "")
JWT_ALGORITHM = "RS256"
NIL_UUID = "00000000-0000-0000-0000-000000000000"

_public_key: str | None = None


@dataclass
class Caller:
    user_id: str
    role: str
    token: str
    issuer: str | None

    @property
    def is_unknown_speaker(self) -> bool:
        return self.user_id == NIL_UUID


def load_public_key() -> str:
    global _public_key
    if _public_key is not None:
        return _public_key
    if not JWT_PUBLIC_KEY_PATH:
        raise RuntimeError("JWT_PUBLIC_KEY_PATH is not set")
    with open(JWT_PUBLIC_KEY_PATH) as f:
        _public_key = f.read()
    return _public_key


def verify(authorization: str | None = Header(default=None)) -> Caller:
    """FastAPI dependency: verify the Bearer JWT. 401 on any failure."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization[len("Bearer "):]
    try:
        payload = jwt.decode(token, load_public_key(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token abgelaufen")
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid token: %s", exc)
        raise HTTPException(status_code=401, detail="Token ungültig")
    except RuntimeError as exc:
        logger.error("JWT public key unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Auth not configured")

    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token ungültig")
    return Caller(
        user_id=str(user_id),
        role=str(payload.get("role") or ""),
        token=token,
        issuer=payload.get("iss"),
    )
