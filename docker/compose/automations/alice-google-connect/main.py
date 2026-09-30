"""
alice-google-connect: FastAPI service for the Google OAuth connection lifecycle (PROJ-86).

nginx proxies /api/google/* → alice-google-connect:8008, forwarding the /google/... path.
All endpoints therefore start with /google/ or are /health.

This service only VERIFIES Alice JWTs (RS256, public key); it never issues them.
Google access/refresh tokens are stored AES-256-CBC encrypted (key: SHA-256(GOOGLE_ENC_KEY)).

Endpoints:
  GET    /health                              - Health check (DB + public key)
  POST   /google/connect/start                - Build a Google consent URL (authenticated)
  GET    /google/callback                     - Google redirect target (no JWT, signed state)
  GET    /google/connections                  - List own connections (authenticated)
  POST   /google/connections/{id}/token       - Internal: valid access token (auto-refresh)
  DELETE /google/connections/{id}             - Disconnect + revoke at Google (authenticated)
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import psycopg2
import psycopg2.extras
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POSTGRES_CONNECTION = os.environ.get("POSTGRES_CONNECTION", "")

# JWT (RS256). This service verifies only — no private key is mounted.
JWT_PUBLIC_KEY_PATH = os.environ.get("JWT_PUBLIC_KEY_PATH", "")
JWT_ALGORITHM = "RS256"

_public_key: str | None = None

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")
GOOGLE_ENC_KEY = os.environ.get("GOOGLE_ENC_KEY", "")
FRONTEND_REDIRECT_URL = os.environ.get("FRONTEND_REDIRECT_URL", "")

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

HTTP_TIMEOUT = 10.0

# Lifetime of the signed OAuth state parameter (consent screens can take a while).
STATE_TTL_SECONDS = 600

# Safety margin: refresh a token that expires within the next 60 s so callers
# never receive a token that dies mid-request.
TOKEN_EXPIRY_MARGIN_SECONDS = 60

# Safety net for the row lock in /token: if contention ever occurs, fail fast
# with a clear DB error instead of waiting forever.
LOCK_TIMEOUT = "5s"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("alice-google-connect")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="alice-google-connect", version="1.0.0")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ConnectStartRequest(BaseModel):
    scopes: list[str]


# ---------------------------------------------------------------------------
# Helpers — Database
# ---------------------------------------------------------------------------
def _get_db_connection():
    if not POSTGRES_CONNECTION:
        raise RuntimeError("POSTGRES_CONNECTION environment variable is not set")
    return psycopg2.connect(POSTGRES_CONNECTION, cursor_factory=psycopg2.extras.RealDictCursor)


# ---------------------------------------------------------------------------
# Helpers — JWT (verify only)
# ---------------------------------------------------------------------------
def _load_public_key() -> str:
    """Load the RSA public key from disk. Cached after first read."""
    global _public_key
    if _public_key is not None:
        return _public_key
    if not JWT_PUBLIC_KEY_PATH:
        raise RuntimeError("JWT_PUBLIC_KEY_PATH environment variable is not set")
    with open(JWT_PUBLIC_KEY_PATH) as f:
        _public_key = f.read()
    return _public_key


def _decode_jwt(token: str) -> dict:
    public_key = _load_public_key()
    return jwt.decode(token, public_key, algorithms=[JWT_ALGORITHM])


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization[len("Bearer "):]


def _require_auth(authorization: str | None) -> dict:
    """Validate Bearer token (any role). Returns JWT payload with user_id."""
    token = _extract_bearer_token(authorization)
    try:
        payload = _decode_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token abgelaufen")
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid token: %s", exc)
        raise HTTPException(status_code=401, detail="Token ungültig")

    if not payload.get("user_id"):
        raise HTTPException(status_code=401, detail="Token ungültig")

    return payload


# ---------------------------------------------------------------------------
# Helpers — Token encryption (AES-256-CBC, same wire format as alice-mail-reader)
# ---------------------------------------------------------------------------
def _get_key() -> bytes:
    if not GOOGLE_ENC_KEY:
        raise RuntimeError("GOOGLE_ENC_KEY not configured")
    return hashlib.sha256(GOOGLE_ENC_KEY.encode()).digest()


def _encrypt_token(plaintext: str) -> str:
    """Return 'iv_hex:ciphertext_hex' (AES-256-CBC, PKCS7)."""
    iv = os.urandom(16)
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_get_key()), modes.CBC(iv)).encryptor()
    return iv.hex() + ":" + (encryptor.update(padded) + encryptor.finalize()).hex()


def _decrypt_token(token_enc: str) -> str:
    iv_hex, enc_hex = token_enc.split(":")
    decryptor = Cipher(algorithms.AES(_get_key()), modes.CBC(bytes.fromhex(iv_hex))).decryptor()
    padded = decryptor.update(bytes.fromhex(enc_hex)) + decryptor.finalize()
    unpadder = sym_padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")


# ---------------------------------------------------------------------------
# Helpers — Signed OAuth state
# ---------------------------------------------------------------------------
# The state binds the Alice user to the consent flow and carries a CSRF nonce.
# It is HMAC-signed with GOOGLE_ENC_KEY: this service holds no JWT private key,
# and the state only has to be verifiable by this same service.
def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign_state_payload(payload_b64: str) -> str:
    return hmac.new(_get_key(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()


def _build_state(user_id: str) -> str:
    payload = {
        "user_id": user_id,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + STATE_TTL_SECONDS,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign_state_payload(payload_b64)}"


def _verify_state(state: str) -> dict:
    """Verify signature + expiry. Raises ValueError on any problem."""
    try:
        payload_b64, signature = state.split(".", 1)
    except ValueError:
        raise ValueError("malformed state")

    if not hmac.compare_digest(signature, _sign_state_payload(payload_b64)):
        raise ValueError("bad state signature")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise ValueError("undecodable state payload")

    if not payload.get("user_id"):
        raise ValueError("state without user_id")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("state expired")

    return payload


# ---------------------------------------------------------------------------
# Helpers — Misc
# ---------------------------------------------------------------------------
def _frontend_redirect(**params: str) -> RedirectResponse:
    """302 back to the Alice settings page with result parameters."""
    separator = "&" if "?" in FRONTEND_REDIRECT_URL else "?"
    # httpx handles the percent-encoding of the query parameters.
    encoded = httpx.URL("http://x", params=params).query.decode("ascii")
    return RedirectResponse(url=f"{FRONTEND_REDIRECT_URL}{separator}{encoded}", status_code=302)


def _row_to_connection(row: dict) -> dict:
    """Public representation of a connection — never contains tokens."""
    return {
        "id": str(row["id"]),
        "google_account": row["google_account"],
        "scopes": list(row["scopes"] or []),
        "status": row["status"],
        "last_error": row["last_error"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


# ---------------------------------------------------------------------------
# Startup checks — fail fast on missing configuration.
# ---------------------------------------------------------------------------
try:
    _load_public_key()
    logger.info("JWT public key loaded successfully (algorithm=%s)", JWT_ALGORITHM)
except Exception as _key_exc:
    logger.critical("JWT public key load failed on startup: %s", _key_exc)
    sys.exit(1)

for _name, _value in (
    ("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID),
    ("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET),
    ("GOOGLE_REDIRECT_URI", GOOGLE_REDIRECT_URI),
    ("GOOGLE_ENC_KEY", GOOGLE_ENC_KEY),
    ("FRONTEND_REDIRECT_URL", FRONTEND_REDIRECT_URL),
):
    if not _value:
        logger.critical("%s is not configured", _name)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Endpoints — Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Health check endpoint."""
    def _check_db() -> bool:
        try:
            conn = _get_db_connection()
            conn.close()
            return True
        except Exception:
            return False

    db_ok = await run_in_threadpool(_check_db)

    key_ok = True
    try:
        _load_public_key()
    except Exception:
        key_ok = False

    return {
        "status": "healthy" if (db_ok and key_ok) else "degraded",
        "db": db_ok,
        "jwt_public_key": key_ok,
    }


# ---------------------------------------------------------------------------
# Endpoints — Consent start
# ---------------------------------------------------------------------------
@app.post("/google/connect/start")
async def connect_start(
    body: ConnectStartRequest,
    authorization: str | None = Header(default=None),
):
    """
    Build the Google authorization URL for the authenticated user.
    access_type=offline + prompt=consent guarantee a refresh_token even on
    repeat consents (needed for the scope-extension flow).
    """
    payload = _require_auth(authorization)
    user_id = payload["user_id"]

    scopes = [s.strip() for s in body.scopes if isinstance(s, str) and s.strip()]
    if not scopes:
        raise HTTPException(status_code=422, detail="Mindestens ein Scope ist erforderlich")
    if len(scopes) > 50:
        raise HTTPException(status_code=422, detail="Maximal 50 Scopes erlaubt")
    for scope in scopes:
        if len(scope) > 200 or not scope.startswith(("https://", "openid", "profile", "email")):
            raise HTTPException(status_code=422, detail=f"Ungültiger Scope: {scope}")

    # openid + email are always requested so the callback can identify the
    # Google account behind the grant.
    effective_scopes = list(dict.fromkeys(["openid", "email", *scopes]))

    auth_url = str(
        httpx.URL(
            GOOGLE_AUTH_ENDPOINT,
            params={
                "client_id": GOOGLE_CLIENT_ID,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "response_type": "code",
                "scope": " ".join(effective_scopes),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": _build_state(user_id),
            },
        )
    )

    logger.info("Consent start for user_id=%s scopes=%s", user_id, effective_scopes)
    return {"auth_url": auth_url}


# ---------------------------------------------------------------------------
# Endpoints — OAuth callback
# ---------------------------------------------------------------------------
@app.get("/google/callback")
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    scope: str | None = None,
):
    """
    Google redirect target. Not JWT-authenticated — the browser arrives from
    Google without an Alice Authorization header; the signed state carries the
    user binding. Any failure redirects back to the frontend without touching
    the database.
    """
    if error:
        logger.info("Callback returned error from Google: %s", error)
        return _frontend_redirect(google="error", reason=error)

    if not state or not code:
        logger.warning("Callback without state or code")
        return _frontend_redirect(google="error", reason="invalid_request")

    try:
        state_payload = _verify_state(state)
    except ValueError as exc:
        logger.warning("Callback state rejected: %s", exc)
        return _frontend_redirect(google="error", reason="invalid_state")

    user_id = state_payload["user_id"]

    # --- Exchange the authorization code for tokens ---
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            token_response = await client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
    except httpx.HTTPError as exc:
        logger.error("Token exchange transport error: %s", exc)
        return _frontend_redirect(google="error", reason="google_unreachable")

    if token_response.status_code != 200:
        logger.error("Token exchange failed (%s): %s", token_response.status_code, token_response.text)
        return _frontend_redirect(google="error", reason="token_exchange_failed")

    token_data = token_response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = int(token_data.get("expires_in", 3600))
    granted_scopes = [s for s in (token_data.get("scope") or scope or "").split(" ") if s]

    if not access_token:
        logger.error("Token exchange response without access_token")
        return _frontend_redirect(google="error", reason="token_exchange_failed")

    # --- Identify the Google account ---
    try:
        google_account = await _fetch_google_account(access_token)
    except Exception as exc:
        logger.error("Userinfo lookup failed: %s", exc)
        return _frontend_redirect(google="error", reason="userinfo_failed")

    # --- Persist (blocking psycopg2 work → worker thread) ---
    ok, reason = await run_in_threadpool(
        _persist_connection, user_id, google_account, access_token, refresh_token,
        expires_in, granted_scopes,
    )
    if not ok:
        return _frontend_redirect(google="error", reason=reason)

    return _frontend_redirect(google="connected", account=google_account)


def _persist_connection(
    user_id: str,
    google_account: str,
    access_token: str,
    refresh_token: str | None,
    expires_in: int,
    granted_scopes: list[str],
) -> tuple[bool, str]:
    """
    Store/update the connection. Synchronous by design — always call through
    run_in_threadpool so the blocking psycopg2 work stays off the event loop.
    Returns (success, error_reason).
    """
    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        return False, "db_unavailable"

    try:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, scopes
                FROM alice.google_connections
                WHERE user_id = %s AND google_account = %s
                FOR UPDATE
                """,
                (user_id, google_account),
            )
            existing = cur.fetchone()

        if existing:
            # Union scopes; only overwrite the refresh token when Google sent a
            # new one (it may omit it on repeat consent).
            merged_scopes = sorted(set(list(existing["scopes"] or [])) | set(granted_scopes))
            with conn.cursor() as cur:
                if refresh_token:
                    cur.execute(
                        """
                        UPDATE alice.google_connections
                           SET scopes = %s,
                               access_token_enc = %s,
                               access_token_expires_at = %s,
                               refresh_token_enc = %s,
                               status = 'active',
                               last_error = NULL
                         WHERE id = %s
                        """,
                        (
                            merged_scopes,
                            _encrypt_token(access_token),
                            expires_at,
                            _encrypt_token(refresh_token),
                            existing["id"],
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE alice.google_connections
                           SET scopes = %s,
                               access_token_enc = %s,
                               access_token_expires_at = %s,
                               status = 'active',
                               last_error = NULL
                         WHERE id = %s
                        """,
                        (merged_scopes, _encrypt_token(access_token), expires_at, existing["id"]),
                    )
            conn.commit()
            logger.info(
                "Updated google connection id=%s user_id=%s account=%s scopes=%s",
                existing["id"], user_id, google_account, merged_scopes,
            )
        else:
            if not refresh_token:
                # Without a refresh token the connection cannot survive an hour.
                logger.error(
                    "New connection for user_id=%s account=%s came without refresh_token",
                    user_id, google_account,
                )
                conn.rollback()
                return False, "no_refresh_token"

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO alice.google_connections
                        (user_id, google_account, scopes, access_token_enc,
                         access_token_expires_at, refresh_token_enc, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'active')
                    RETURNING id
                    """,
                    (
                        user_id,
                        google_account,
                        sorted(set(granted_scopes)),
                        _encrypt_token(access_token),
                        expires_at,
                        _encrypt_token(refresh_token),
                    ),
                )
                created = cur.fetchone()
            conn.commit()
            logger.info(
                "Created google connection id=%s user_id=%s account=%s",
                created["id"], user_id, google_account,
            )

        return True, ""

    except Exception as exc:
        conn.rollback()
        logger.error("Callback persistence error: %s", exc)
        return False, "storage_failed"
    finally:
        conn.close()


async def _fetch_google_account(access_token: str) -> str:
    """
    Resolve the Google account identifier (email) for a fresh access token.
    Uses the OpenID userinfo endpoint rather than decoding the id_token: it
    needs no JWKS fetching/signature handling and works identically whether or
    not the grant included an id_token.
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code != 200:
        raise RuntimeError(f"userinfo returned {response.status_code}: {response.text}")

    data = response.json()
    account = data.get("email") or data.get("sub")
    if not account:
        raise RuntimeError("userinfo response contained neither email nor sub")
    return account


# ---------------------------------------------------------------------------
# Endpoints — Connection list
# ---------------------------------------------------------------------------
@app.get("/google/connections")
async def list_connections(authorization: str | None = Header(default=None)):
    """List the caller's own connections. Never returns tokens."""
    payload = _require_auth(authorization)
    user_id = payload["user_id"]

    return await run_in_threadpool(_list_connections_sync, user_id)


def _list_connections_sync(user_id: str) -> list[dict]:
    """Synchronous by design — call through run_in_threadpool."""
    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, google_account, scopes, status, last_error, created_at, updated_at
                FROM alice.google_connections
                WHERE user_id = %s
                ORDER BY created_at ASC
                LIMIT 100
                """,
                (user_id,),
            )
            rows = cur.fetchall()

        return [_row_to_connection(row) for row in rows]

    except Exception as exc:
        logger.error("list_connections error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Endpoints — Internal token retrieval
# ---------------------------------------------------------------------------
@app.post("/google/connections/{connection_id}/token")
async def get_access_token(
    connection_id: uuid.UUID,
    authorization: str | None = Header(default=None),
):
    """
    Internal endpoint for downstream agents (PROJ-87/88/89): return a currently
    valid access token, refreshing it transparently when expired.

    Authenticated with the end user's JWT and scoped to that user: the agent
    calling this always acts on behalf of a concrete Alice user and can forward
    that user's token, so there is no reason to widen the blast radius by
    allowing cross-user token retrieval.

    The expiry check, the refresh and the write-back all happen inside one
    transaction holding a row lock, so two parallel agent calls cannot refresh
    (and thereby invalidate each other's) refresh token.
    """
    payload = _require_auth(authorization)
    user_id = payload["user_id"]

    return await run_in_threadpool(_get_access_token_sync, str(connection_id), user_id)


def _get_access_token_sync(connection_id: str, user_id: str) -> dict:
    """
    Lock the row, decide on refresh, call Google and write back — all inside one
    transaction so parallel callers cannot refresh twice.

    Synchronous by design: it must run in a worker thread (run_in_threadpool),
    never on the event loop. The row lock is held across a *blocking* HTTP call
    to Google (httpx.Client); awaiting inside the transaction from the event
    loop is exactly what deadlocked the service before (BUG-01).
    """
    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            # Safety net: never wait forever for the row lock (BUG-01).
            # SET does not accept bind parameters — use set_config() instead.
            cur.execute("SELECT set_config('lock_timeout', %s, TRUE)", (LOCK_TIMEOUT,))
            cur.execute(
                """
                SELECT id, google_account, status, access_token_enc,
                       access_token_expires_at, refresh_token_enc
                FROM alice.google_connections
                WHERE id = %s AND user_id = %s
                FOR UPDATE
                """,
                (connection_id, user_id),
            )
            row = cur.fetchone()

        if not row:
            # Also covers other users' connections — never reveal their existence.
            raise HTTPException(status_code=404, detail="Connection nicht gefunden")

        if row["status"] == "error":
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "reauth_required",
                    "detail": "Die Google-Verbindung ist fehlerhaft und muss neu verbunden werden.",
                },
            )

        now = datetime.now(timezone.utc)
        expires_at = row["access_token_expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        # Still valid (with safety margin) → hand it out unchanged.
        if expires_at - timedelta(seconds=TOKEN_EXPIRY_MARGIN_SECONDS) > now:
            access_token = _decrypt_token(row["access_token_enc"])
            conn.commit()
            return {
                "access_token": access_token,
                "expires_at": expires_at.isoformat(),
                "google_account": row["google_account"],
            }

        # --- Refresh ---
        refresh_token = _decrypt_token(row["refresh_token_enc"])
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                refresh_response = client.post(
                    GOOGLE_TOKEN_ENDPOINT,
                    data={
                        "client_id": GOOGLE_CLIENT_ID,
                        "client_secret": GOOGLE_CLIENT_SECRET,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
        except httpx.HTTPError as exc:
            # Transport problem — not the user's fault, keep the connection active.
            conn.rollback()
            logger.error("Refresh transport error for connection=%s: %s", connection_id, exc)
            raise HTTPException(status_code=502, detail="Google ist derzeit nicht erreichbar")

        if refresh_response.status_code != 200:
            # Google rejected the refresh token (invalid_grant, revoked, ...).
            error_body = refresh_response.text[:500]
            logger.warning(
                "Refresh rejected for connection=%s (%s): %s",
                connection_id, refresh_response.status_code, error_body,
            )
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE alice.google_connections
                       SET status = 'error', last_error = %s
                     WHERE id = %s
                    """,
                    (f"Refresh failed ({refresh_response.status_code}): {error_body}", connection_id),
                )
            conn.commit()
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "reauth_required",
                    "detail": "Google hat den Refresh abgelehnt — die Verbindung muss neu hergestellt werden.",
                },
            )

        refresh_data = refresh_response.json()
        new_access_token = refresh_data.get("access_token")
        if not new_access_token:
            conn.rollback()
            logger.error("Refresh response without access_token for connection=%s", connection_id)
            raise HTTPException(status_code=502, detail="Ungültige Antwort von Google")

        new_expires_at = now + timedelta(seconds=int(refresh_data.get("expires_in", 3600)))
        # Google may rotate the refresh token; store it when present.
        rotated_refresh_token = refresh_data.get("refresh_token")

        with conn.cursor() as cur:
            if rotated_refresh_token:
                cur.execute(
                    """
                    UPDATE alice.google_connections
                       SET access_token_enc = %s,
                           access_token_expires_at = %s,
                           refresh_token_enc = %s,
                           status = 'active',
                           last_error = NULL
                     WHERE id = %s
                    """,
                    (
                        _encrypt_token(new_access_token),
                        new_expires_at,
                        _encrypt_token(rotated_refresh_token),
                        connection_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE alice.google_connections
                       SET access_token_enc = %s,
                           access_token_expires_at = %s,
                           status = 'active',
                           last_error = NULL
                     WHERE id = %s
                    """,
                    (_encrypt_token(new_access_token), new_expires_at, connection_id),
                )
        conn.commit()

        logger.info("Refreshed access token for connection=%s", connection_id)
        return {
            "access_token": new_access_token,
            "expires_at": new_expires_at.isoformat(),
            "google_account": row["google_account"],
        }

    except HTTPException:
        raise
    except psycopg2.errors.LockNotAvailable as exc:
        # lock_timeout hit: another refresh for this connection is in flight.
        conn.rollback()
        logger.warning("Lock timeout on connection=%s: %s", connection_id, exc)
        raise HTTPException(
            status_code=503,
            detail="Token wird gerade aktualisiert — bitte erneut versuchen",
        )
    except Exception as exc:
        conn.rollback()
        logger.error("get_access_token error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Endpoints — Disconnect
# ---------------------------------------------------------------------------
@app.delete("/google/connections/{connection_id}")
async def delete_connection(
    connection_id: uuid.UUID,
    authorization: str | None = Header(default=None),
):
    """
    Disconnect a connection: revoke the grant at Google (best effort) and delete
    the local row. A failing revoke call is logged but never blocks the delete —
    "disconnected" must always hold locally.
    """
    payload = _require_auth(authorization)
    user_id = payload["user_id"]
    connection_id_str = str(connection_id)

    refresh_token_enc = await run_in_threadpool(
        _load_connection_refresh_token, connection_id_str, user_id
    )

    # Best-effort revoke at Google. No row lock is held here, so the outbound
    # call stays a normal async await on the event loop.
    try:
        refresh_token = _decrypt_token(refresh_token_enc)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            revoke_response = await client.post(
                GOOGLE_REVOKE_ENDPOINT,
                data={"token": refresh_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if revoke_response.status_code >= 300:
            logger.warning(
                "Google revoke for connection=%s returned %s: %s",
                connection_id_str, revoke_response.status_code, revoke_response.text[:200],
            )
    except Exception as exc:
        logger.warning("Google revoke for connection=%s failed: %s", connection_id_str, exc)

    await run_in_threadpool(_delete_connection_row, connection_id_str, user_id)

    logger.info("Deleted google connection id=%s user_id=%s", connection_id_str, user_id)
    return {"success": True}


def _load_connection_refresh_token(connection_id: str, user_id: str) -> str:
    """Synchronous by design — call through run_in_threadpool."""
    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, refresh_token_enc
                FROM alice.google_connections
                WHERE id = %s AND user_id = %s
                """,
                (connection_id, user_id),
            )
            row = cur.fetchone()

        if not row:
            # Never reveal that another user's connection exists.
            raise HTTPException(status_code=404, detail="Connection nicht gefunden")

        return row["refresh_token_enc"]

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("delete_connection lookup error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


def _delete_connection_row(connection_id: str, user_id: str) -> None:
    """Synchronous by design — call through run_in_threadpool."""
    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM alice.google_connections WHERE id = %s AND user_id = %s",
                (connection_id, user_id),
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("delete_connection error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()
