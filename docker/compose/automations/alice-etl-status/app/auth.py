"""
Admin access (PROJ-122): RS256 JWT from alice-auth, verified with its public key, and the
role looked up in alice.users on every request. A token outlives a role change; reading the
role from the database makes a downgrade effective with the next request (EC-8).

No/invalid/expired token → 401. Inactive user or role other than admin → 403.
"""
from __future__ import annotations

import logging

import jwt

logger = logging.getLogger("alice-etl-status.auth")


class Unauthorized(Exception):
    pass


class Forbidden(Exception):
    pass


class Auth:
    def __init__(self, public_key_path: str):
        self.path = public_key_path
        self._key: str | None = None

    def key(self) -> str:
        if self._key is None:
            if not self.path:
                raise RuntimeError("JWT_PUBLIC_KEY_PATH is not set")
            with open(self.path) as f:
                self._key = f.read()
        return self._key

    def verify(self, authorization: str | None) -> str:
        """Verified user id from the Bearer token."""
        if not authorization or not authorization.startswith("Bearer "):
            raise Unauthorized("Anmeldung erforderlich")
        try:
            payload = jwt.decode(authorization[len("Bearer "):], self.key(), algorithms=["RS256"])
        except jwt.ExpiredSignatureError:
            raise Unauthorized("Token abgelaufen")
        except jwt.InvalidTokenError as exc:
            logger.warning("Invalid token: %s", exc.__class__.__name__)
            raise Unauthorized("Token ungültig")
        user_id = payload.get("user_id") or payload.get("sub")
        if not user_id:
            raise Unauthorized("Token ungültig")
        return str(user_id)

    async def admin(self, pool, authorization: str | None) -> dict:
        """{id, name} of the active admin behind the token."""
        user_id = self.verify(authorization)
        try:
            row = await pool.fetchrow(
                "SELECT id::text AS id, username, display_name, role, is_active FROM alice.users "
                "WHERE id = $1::uuid", user_id)
        except (ValueError, TypeError):
            raise Unauthorized("Token ungültig")
        if row is None or not row["is_active"] or row["role"] != "admin":
            raise Forbidden("Admin-Zugriff erforderlich")
        return {"id": row["id"], "name": row["username"]}
