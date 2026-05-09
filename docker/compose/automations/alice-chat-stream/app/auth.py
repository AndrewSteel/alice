"""
JWT authentication (RS256, public key from file).

alice-auth signs tokens with the RSA private key; this service verifies
them with the corresponding public key. The private key never leaves
alice-auth — only the public key is mounted here.

Token shape (from alice-auth/_create_jwt):
    { "user_id": str, "username": str, "role": str, "iat": int, "exp": int }
"""
from __future__ import annotations

import logging
import os

import jwt
from fastapi import Header, HTTPException

logger = logging.getLogger("alice-chat-stream.auth")

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


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization[len("Bearer "):]


def verify_jwt(authorization: str | None = Header(default=None)) -> dict:
    """
    FastAPI dependency: verify Bearer JWT and return the payload.

    Raises HTTP 401 on any failure. user_id MUST come from the verified
    payload — never from a request body.
    """
    try:
        public_key = _load_public_key()
    except Exception as exc:
        logger.error("Failed to load JWT public key: %s", exc)
        raise HTTPException(status_code=503, detail="Auth not configured")

    token = _extract_bearer_token(authorization)
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
