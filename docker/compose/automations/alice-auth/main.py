"""
alice-auth: FastAPI service for JWT authentication.

Endpoints:
  GET  /health              - Health check
  POST /auth/login          - Verify username + password, return JWT
  GET  /auth/validate       - Verify Bearer token, return user info
  POST /auth/logout         - Log logout event (fire-and-forget)
  POST /auth/hash-password  - Utility: hash a plaintext password (admin use only)
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POSTGRES_CONNECTION = os.environ.get("POSTGRES_CONNECTION", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("alice-auth")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="alice-auth", version="1.0.0")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class HashPasswordRequest(BaseModel):
    password: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_db_connection():
    if not POSTGRES_CONNECTION:
        raise RuntimeError("POSTGRES_CONNECTION environment variable is not set")
    return psycopg2.connect(POSTGRES_CONNECTION, cursor_factory=psycopg2.extras.RealDictCursor)


def _create_jwt(user_id: str, username: str, role: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable is not set")
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRY_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str) -> dict:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable is not set")
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization[len("Bearer "):]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Health check endpoint."""
    db_ok = False
    try:
        conn = _get_db_connection()
        conn.close()
        db_ok = True
    except Exception:
        pass

    if not JWT_SECRET:
        return {"status": "degraded", "db": db_ok, "jwt_secret": False}

    return {"status": "healthy" if db_ok else "degraded", "db": db_ok, "jwt_secret": True}


@app.post("/auth/login")
async def login(body: LoginRequest):
    """
    Verify username + password and return a signed JWT.
    Returns HTTP 401 with generic message on any failure (no username/password hint).
    """
    username = body.username.strip()
    password = body.password

    if not username or not password:
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, role, password_hash, is_active
                FROM alice.users
                WHERE username = %s
                """,
                (username,),
            )
            row = cur.fetchone()

        if not row:
            logger.info("Login failed: unknown username=%s", username)
            raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

        if not row["is_active"]:
            logger.info("Login failed: inactive user=%s", username)
            raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

        if not row["password_hash"]:
            logger.warning("Login failed: no password_hash set for user=%s", username)
            raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

        # bcrypt compare — safe against timing attacks
        password_ok = bcrypt.checkpw(
            password.encode("utf-8"),
            row["password_hash"].encode("utf-8"),
        )

        if not password_ok:
            logger.info("Login failed: wrong password for user=%s", username)
            raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

        # Update last_login_at
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE alice.users SET last_login_at = NOW() WHERE id = %s",
                (str(row["id"]),),
            )
        conn.commit()

        token = _create_jwt(
            user_id=str(row["id"]),
            username=row["username"],
            role=row["role"],
        )

        logger.info("Login successful: user=%s", username)
        return {
            "token": token,
            "user": {
                "id": str(row["id"]),
                "username": row["username"],
                "role": row["role"],
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Login error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.get("/auth/validate")
async def validate(authorization: str | None = Header(default=None)):
    """
    Verify a Bearer JWT. Returns user info if valid, HTTP 401 if not.
    Also checks that the user is still active in the database.
    """
    token = _extract_bearer_token(authorization)

    try:
        payload = _decode_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token abgelaufen")
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid token: %s", exc)
        raise HTTPException(status_code=401, detail="Token ungültig")

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token ungültig")

    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_active FROM alice.users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()

        if not row or not row["is_active"]:
            raise HTTPException(status_code=401, detail="Account deaktiviert")

        return {
            "valid": True,
            "user": {
                "id": payload["user_id"],
                "username": payload["username"],
                "role": payload["role"],
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Validate error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.post("/auth/logout")
async def logout(authorization: str | None = Header(default=None)):
    """
    Log a logout event. Fire-and-forget — always returns success.
    No token blacklisting in Phase 1.5.
    """
    try:
        token = _extract_bearer_token(authorization)
        payload = _decode_jwt(token)
        logger.info("Logout: user=%s", payload.get("username", "unknown"))
    except Exception:
        # Fire-and-forget: ignore invalid tokens on logout
        pass

    return {"success": True}


@app.post("/auth/hash-password")
async def hash_password(
    body: HashPasswordRequest,
    authorization: str | None = Header(default=None),
):
    """
    Utility endpoint: hash a plaintext password with bcrypt (cost 12).
    Use this to generate hashes for seed-passwords.sql.
    Requires a valid admin JWT for authentication.
    """
    token = _extract_bearer_token(authorization)
    try:
        payload = _decode_jwt(token)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token ungültig")

    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin-Berechtigung erforderlich")

    if not body.password:
        raise HTTPException(status_code=400, detail="Password must not be empty")

    hashed = bcrypt.hashpw(body.password.encode("utf-8"), bcrypt.gensalt(rounds=12))
    return {"hash": hashed.decode("utf-8")}
