"""JWT authentication (RS256) — identical pattern to alice-chat-stream."""
from __future__ import annotations

import logging
import os

import jwt
from fastapi import Header, HTTPException

logger = logging.getLogger("alice-dms-thumbnailer.auth")

JWT_PUBLIC_KEY_PATH = os.environ.get("JWT_PUBLIC_KEY_PATH", "")
JWT_ALGORITHM = "RS256"
_public_key: str | None = None


def _load_public_key() -> str:
    global _public_key
    if _public_key is not None:
        return _public_key
    if not JWT_PUBLIC_KEY_PATH:
        raise RuntimeError("JWT_PUBLIC_KEY_PATH is not set")
    with open(JWT_PUBLIC_KEY_PATH) as f:
        _public_key = f.read()
    return _public_key


def verify_jwt(authorization: str | None = Header(default=None)) -> dict:
    try:
        public_key = _load_public_key()
    except Exception as exc:
        logger.error("Failed to load JWT public key: %s", exc)
        raise HTTPException(status_code=503, detail="Auth not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization[len("Bearer "):]
    try:
        payload = jwt.decode(token, public_key, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token abgelaufen")
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid token: %s", exc)
        raise HTTPException(status_code=401, detail="Token ungültig")

    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token ungültig")
    payload["user_id"] = str(user_id)
    return payload
