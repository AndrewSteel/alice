"""
JWT authentication (RS256, public key from file).

alice-auth signs tokens with the RSA private key; this service verifies
them with the corresponding public key. The private key never leaves
alice-auth — only the public key is mounted here.

WebApp clients connect over WebSocket and cannot set an Authorization
header reliably from browser JS, so the token may also be passed as a
`token` query parameter. The Wyoming endpoint does not use JWT — it
trusts the internal Docker network and authorises via device mapping.

Token shape (from alice-auth/_create_jwt):
    { "user_id": str, "username": str, "role": str, "iat": int, "exp": int }
"""
from __future__ import annotations

import logging

import jwt

from . import config

logger = logging.getLogger("alice-speech-gateway.auth")

_public_key: str | None = None


class AuthError(Exception):
    """Raised when a token is missing, malformed, expired or invalid."""


def _load_public_key() -> str:
    global _public_key
    if _public_key is not None:
        return _public_key
    if not config.JWT_PUBLIC_KEY_PATH:
        raise RuntimeError("JWT_PUBLIC_KEY_PATH is not set")
    with open(config.JWT_PUBLIC_KEY_PATH) as f:
        _public_key = f.read()
    return _public_key


def verify_token(token: str | None) -> dict:
    """
    Verify a raw JWT string and return the payload.

    Raises AuthError on any failure. user_id MUST come from the verified
    payload — never from a request body or query string.
    """
    if not token:
        raise AuthError("Token fehlt")

    try:
        public_key = _load_public_key()
    except Exception as exc:  # noqa: BLE001 — config error, surface clearly
        logger.error("Failed to load JWT public key: %s", exc)
        raise AuthError("Authentifizierung nicht konfiguriert") from exc

    try:
        payload = jwt.decode(token, public_key, algorithms=[config.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token abgelaufen") from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid token: %s", exc)
        raise AuthError("Token ungültig") from exc

    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        raise AuthError("Token ungültig")

    payload["user_id"] = str(user_id)
    return payload


def extract_ws_token(headers: dict, query_params: dict) -> str | None:
    """
    Pull the JWT from a WebSocket handshake.

    Order of preference: Authorization: Bearer header, then ?token= query
    parameter (browser fallback).
    """
    authorization = headers.get("authorization") or headers.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        return authorization[len("Bearer "):]
    return query_params.get("token")
