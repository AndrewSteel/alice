"""
alice-auth: FastAPI service for JWT authentication.

nginx proxies /api/auth/* → alice-auth:8002, forwarding the /auth/... path.
All endpoints therefore start with /auth/ or are /health.

Endpoints:
  GET  /health                             - Health check
  POST /auth/login                         - Verify username + password, return JWT
  GET  /auth/validate                      - Verify Bearer token, return user info
  POST /auth/logout                        - Log logout event (fire-and-forget)
  POST /auth/hash-password                 - Utility: hash a plaintext password (admin use only)
  POST /auth/change-password               - Change password (required when must_change_password=TRUE)

  GET    /auth/admin/users                 - List all users (admin only)
  POST   /auth/admin/users                 - Create user + OTP + send email (admin only)
  POST   /auth/admin/users/{id}/reset-otp  - Generate new OTP + send email (admin only)
  PATCH  /auth/admin/users/{id}/status     - Activate / deactivate user (admin only)
  DELETE /auth/admin/users/{id}            - Permanently delete user (admin only)
"""

import collections
import logging
import os
import re
import secrets
import smtplib
import string
import threading
import time
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import bcrypt
import jwt
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POSTGRES_CONNECTION = os.environ.get("POSTGRES_CONNECTION", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "Alice <alice@example.com>")
ALICE_BASE_URL = os.environ.get("ALICE_BASE_URL", "https://alice.example.com")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("alice-auth")

# ---------------------------------------------------------------------------
# In-memory rate limiter (admin endpoints: 60 requests / 60 s per IP)
# ---------------------------------------------------------------------------
_rate_lock = threading.Lock()
_rate_buckets: dict[str, list[float]] = collections.defaultdict(list)
_ADMIN_RATE_LIMIT = 60      # max requests
_ADMIN_RATE_WINDOW = 60.0   # per second window


def _check_admin_rate_limit(request: Request) -> None:
    """Raise HTTP 429 if the caller IP exceeds the admin rate limit."""
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_lock:
        timestamps = _rate_buckets[ip]
        # Evict entries outside the window
        cutoff = now - _ADMIN_RATE_WINDOW
        _rate_buckets[ip] = [t for t in timestamps if t > cutoff]
        if len(_rate_buckets[ip]) >= _ADMIN_RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Too many requests — bitte warten.")
        _rate_buckets[ip].append(now)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="alice-auth", version="1.1.0")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class HashPasswordRequest(BaseModel):
    password: str


class CreateUserRequest(BaseModel):
    username: str
    email: str
    role: str
    # Optional profile fields
    name: str | None = None
    rolle: str | None = None
    anrede: str | None = None
    sprache: str | None = None
    detailgrad: str | None = None


class UpdateStatusRequest(BaseModel):
    is_active: bool


class ChangePasswordRequest(BaseModel):
    new_password: str


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


def _require_admin(authorization: str | None) -> dict:
    """Validate Bearer token and verify role=admin. Returns JWT payload."""
    token = _extract_bearer_token(authorization)
    try:
        payload = _decode_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token abgelaufen")
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid token: %s", exc)
        raise HTTPException(status_code=401, detail="Token ungültig")

    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin-Berechtigung erforderlich")

    return payload


def _generate_otp() -> str:
    """Generate a cryptographically random 8-character alphanumeric OTP."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _validate_email_format(email: str) -> bool:
    """Basic email format validation."""
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return bool(re.match(pattern, email))


def _check_mx_record(domain: str) -> tuple[bool, bool]:
    """
    Check if domain has MX records.
    Returns (has_mx: bool, timed_out: bool).
    """
    try:
        import dns.resolver
        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 5
        resolver.resolve(domain, "MX")
        return True, False
    except Exception as exc:
        exc_name = type(exc).__name__
        if "NoAnswer" in exc_name or "NXDOMAIN" in exc_name:
            return False, False
        # Timeout or any other error → best-effort, don't block
        logger.warning("MX lookup for %s failed (best-effort): %s", domain, exc)
        return True, True


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _send_otp_email(email: str, username: str, display_name: str | None, otp: str) -> None:
    """Send OTP email via SMTP. Raises on failure."""
    name = display_name or username
    body = f"""Hallo {name},

dein Alice-Konto wurde eingerichtet. Dein Einmal-Passwort lautet:

  {otp}

Bitte melde dich unter {ALICE_BASE_URL} an und ändere das Passwort
beim ersten Login. Das Passwort ist nur einmal verwendbar.

Viele Grüße,
Alice"""

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Dein Alice-Zugang"
    msg["From"] = SMTP_FROM
    msg["To"] = email

    # Port 465 = implicit SSL (SMTP_SSL); port 587 = STARTTLS
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)


# ---------------------------------------------------------------------------
# Endpoints — Health
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


# ---------------------------------------------------------------------------
# Endpoints — Auth
# ---------------------------------------------------------------------------
@app.post("/auth/login")
async def login(body: LoginRequest):
    """
    Verify username + password and return a signed JWT.
    Returns HTTP 401 with generic message on any failure (no username/password hint).
    When must_change_password=TRUE, the response includes that flag.
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
                SELECT id, username, role, password_hash, is_active, must_change_password
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
        response = {
            "token": token,
            "user": {
                "id": str(row["id"]),
                "username": row["username"],
                "role": row["role"],
            },
        }
        if row["must_change_password"]:
            response["must_change_password"] = True

        return response

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
                "SELECT is_active, must_change_password FROM alice.users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()

        if not row or not row["is_active"]:
            raise HTTPException(status_code=401, detail="Account deaktiviert")

        response: dict = {
            "valid": True,
            "user": {
                "id": payload["user_id"],
                "username": payload["username"],
                "role": payload["role"],
            },
        }
        if row["must_change_password"]:
            response["must_change_password"] = True
        return response

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
    _require_admin(authorization)

    if not body.password:
        raise HTTPException(status_code=400, detail="Password must not be empty")

    hashed = bcrypt.hashpw(body.password.encode("utf-8"), bcrypt.gensalt(rounds=12))
    return {"hash": hashed.decode("utf-8")}


@app.post("/auth/change-password")
async def change_password(
    body: ChangePasswordRequest,
    authorization: str | None = Header(default=None),
):
    """
    Change own password. Only works when must_change_password=TRUE.
    New password must be >= 8 chars and differ from the current OTP.
    Clears must_change_password on success.
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

    new_password = body.new_password
    if not new_password or len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Das Passwort muss mindestens 8 Zeichen lang sein")

    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT password_hash, must_change_password, is_active FROM alice.users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()

        if not row or not row["is_active"]:
            raise HTTPException(status_code=401, detail="Account nicht gefunden oder deaktiviert")

        if not row["must_change_password"]:
            raise HTTPException(status_code=400, detail="Passwortänderung ist für diesen Account nicht erforderlich")

        # New password must differ from the current OTP
        if row["password_hash"] and bcrypt.checkpw(
            new_password.encode("utf-8"),
            row["password_hash"].encode("utf-8"),
        ):
            raise HTTPException(status_code=400, detail="Das neue Passwort darf nicht dem Einmal-Passwort entsprechen")

        new_hash = _hash_password(new_password)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE alice.users SET password_hash = %s, must_change_password = FALSE WHERE id = %s",
                (new_hash, user_id),
            )
        conn.commit()

        logger.info("Password changed successfully for user_id=%s", user_id)
        return {"success": True}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Change-password error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Endpoints — Admin user management
# ---------------------------------------------------------------------------
@app.get("/auth/admin/users")
async def admin_list_users(request: Request, authorization: str | None = Header(default=None)):
    """List all users. Admin only. Never returns password_hash."""
    _check_admin_rate_limit(request)
    _require_admin(authorization)

    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, display_name, email, role,
                       is_active, must_change_password, created_at, last_login_at
                FROM alice.users
                ORDER BY created_at ASC
                """
            )
            rows = cur.fetchall()

        return [
            {
                "id": str(r["id"]),
                "username": r["username"],
                "display_name": r["display_name"],
                "email": r["email"],
                "role": r["role"],
                "is_active": r["is_active"],
                "must_change_password": r["must_change_password"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "last_login_at": r["last_login_at"].isoformat() if r["last_login_at"] else None,
            }
            for r in rows
        ]

    except Exception as exc:
        logger.error("admin_list_users error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.post("/auth/admin/users", status_code=201)
async def admin_create_user(
    request: Request,
    body: CreateUserRequest,
    authorization: str | None = Header(default=None),
):
    """
    Create a new user. Generates OTP, sends it via email.
    Initialises permissions from role template and creates user_profiles entry.
    Rolls back user creation if email sending fails.
    """
    _check_admin_rate_limit(request)
    _require_admin(authorization)

    # Validate role
    valid_roles = {"admin", "user", "guest", "child"}
    if body.role not in valid_roles:
        raise HTTPException(status_code=422, detail=f"Ungültige Rolle. Erlaubt: {', '.join(valid_roles)}")

    # Validate optional preference values
    if body.anrede and body.anrede not in {"du", "sie"}:
        raise HTTPException(status_code=422, detail="Ungültige Anrede. Erlaubt: du, sie")
    if body.sprache and body.sprache not in {"deutsch", "englisch"}:
        raise HTTPException(status_code=422, detail="Ungültige Sprache. Erlaubt: deutsch, englisch")
    if body.detailgrad and body.detailgrad not in {"technisch", "normal", "einfach", "kindlich"}:
        raise HTTPException(status_code=422, detail="Ungültiger Detailgrad. Erlaubt: technisch, normal, einfach, kindlich")

    # Validate email format
    if not _validate_email_format(body.email):
        raise HTTPException(status_code=422, detail="Ungültiges E-Mail-Format")

    # MX record check
    domain = body.email.split("@", 1)[1]
    has_mx, timed_out = _check_mx_record(domain)
    mx_warning = None
    if not has_mx and not timed_out:
        raise HTTPException(status_code=422, detail="E-Mail-Domain akzeptiert keine E-Mails (kein MX-Record)")
    if timed_out:
        mx_warning = "MX-Lookup Timeout — E-Mail-Domain konnte nicht vollständig geprüft werden"

    # Generate OTP
    otp = _generate_otp()
    otp_hash = _hash_password(otp)

    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        # Insert user
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO alice.users (username, display_name, email, role, password_hash, must_change_password)
                    VALUES (%s, %s, %s, %s, %s, TRUE)
                    RETURNING id, username, display_name, email, role,
                              is_active, must_change_password, created_at, last_login_at
                    """,
                    (body.username, body.name or None, body.email, body.role, otp_hash),
                )
            except psycopg2.errors.UniqueViolation as exc:
                conn.rollback()
                constraint = exc.diag.constraint_name or ""
                if "email" in constraint:
                    detail = "E-Mail-Adresse ist bereits vergeben"
                else:
                    detail = "Benutzername ist bereits vergeben"
                raise HTTPException(status_code=409, detail=detail)

            new_user = cur.fetchone()
            user_id = new_user["id"]

        # Init permissions from role template
        with conn.cursor() as cur:
            cur.execute("SELECT alice.init_user_permissions(%s, %s)", (str(user_id), body.role))

        # Create user_profiles entry with facts + preferences
        facts: dict = {}
        if body.name:
            facts["name"] = body.name
        if body.rolle:
            facts["rolle"] = body.rolle

        preferences: dict = {}
        if body.anrede:
            preferences["anrede"] = body.anrede
        if body.sprache:
            preferences["sprache"] = body.sprache
        if body.detailgrad:
            preferences["detailgrad"] = body.detailgrad

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alice.user_profiles (user_id, facts, preferences)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    facts = EXCLUDED.facts,
                    preferences = EXCLUDED.preferences,
                    last_updated = NOW()
                """,
                (str(user_id), psycopg2.extras.Json(facts), psycopg2.extras.Json(preferences)),
            )

        # Attempt to send email — rollback on failure
        try:
            _send_otp_email(
                email=body.email,
                username=body.username,
                display_name=body.name,
                otp=otp,
            )
        except Exception as smtp_exc:
            conn.rollback()
            logger.error("SMTP error for new user %s: %s", body.username, smtp_exc)
            raise HTTPException(
                status_code=500,
                detail=f"E-Mail-Versand fehlgeschlagen — Nutzer wurde nicht angelegt. SMTP prüfen. ({smtp_exc})",
            )

        conn.commit()
        logger.info("Admin created user: %s (role=%s)", body.username, body.role)

        response = {
            "id": str(new_user["id"]),
            "username": new_user["username"],
            "display_name": new_user["display_name"],
            "email": new_user["email"],
            "role": new_user["role"],
            "is_active": new_user["is_active"],
            "must_change_password": new_user["must_change_password"],
            "created_at": new_user["created_at"].isoformat() if new_user["created_at"] else None,
            "last_login_at": None,
        }
        if mx_warning:
            response["warning"] = mx_warning
        return response

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.error("admin_create_user error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.post("/auth/admin/users/{user_id}/reset-otp", status_code=200)
async def admin_reset_otp(
    request: Request,
    user_id: str,
    authorization: str | None = Header(default=None),
):
    """Generate a new OTP for the user and send it via email. Admin only."""
    _check_admin_rate_limit(request)
    _require_admin(authorization)

    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, email, display_name FROM alice.users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Nutzer nicht gefunden")

        if not row["email"]:
            raise HTTPException(status_code=400, detail="Nutzer hat keine E-Mail-Adresse hinterlegt")

        otp = _generate_otp()
        otp_hash = _hash_password(otp)

        # Attempt email before writing to DB
        try:
            _send_otp_email(
                email=row["email"],
                username=row["username"],
                display_name=row["display_name"],
                otp=otp,
            )
        except Exception as smtp_exc:
            logger.error("SMTP error on OTP reset for user %s: %s", row["username"], smtp_exc)
            raise HTTPException(
                status_code=500,
                detail=f"E-Mail-Versand fehlgeschlagen — SMTP prüfen. ({smtp_exc})",
            )

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE alice.users SET password_hash = %s, must_change_password = TRUE WHERE id = %s",
                (otp_hash, user_id),
            )
        conn.commit()

        logger.info("OTP reset for user_id=%s (%s)", user_id, row["username"])
        return {"success": True}

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.error("admin_reset_otp error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.patch("/auth/admin/users/{user_id}/status", status_code=200)
async def admin_update_status(
    request: Request,
    user_id: str,
    body: UpdateStatusRequest,
    authorization: str | None = Header(default=None),
):
    """Activate or deactivate a user. Admin cannot deactivate their own account."""
    _check_admin_rate_limit(request)
    admin_payload = _require_admin(authorization)

    # Prevent self-deactivation
    if admin_payload.get("user_id") == user_id:
        raise HTTPException(status_code=403, detail="Der eigene Admin-Account kann nicht deaktiviert werden")

    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE alice.users SET is_active = %s WHERE id = %s RETURNING id",
                (body.is_active, user_id),
            )
            updated = cur.fetchone()

        if not updated:
            raise HTTPException(status_code=404, detail="Nutzer nicht gefunden")

        conn.commit()
        logger.info(
            "Admin set user_id=%s is_active=%s (by %s)",
            user_id, body.is_active, admin_payload.get("username"),
        )
        return {"success": True, "is_active": body.is_active}

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.error("admin_update_status error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.delete("/auth/admin/users/{user_id}", status_code=204)
async def admin_delete_user(
    request: Request,
    user_id: str,
    authorization: str | None = Header(default=None),
):
    """Permanently delete a user and all related data (CASCADE). Admin cannot delete own account."""
    _check_admin_rate_limit(request)
    admin_payload = _require_admin(authorization)

    # Prevent self-deletion
    if admin_payload.get("user_id") == user_id:
        raise HTTPException(status_code=403, detail="Der eigene Admin-Account kann nicht gelöscht werden")

    try:
        conn = _get_db_connection()
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM alice.users WHERE id = %s RETURNING username",
                (user_id,),
            )
            deleted = cur.fetchone()

        if not deleted:
            raise HTTPException(status_code=404, detail="Nutzer nicht gefunden")

        # user_profiles.user_id is VARCHAR — no FK cascade, delete explicitly
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM alice.user_profiles WHERE user_id = %s",
                (user_id,),
            )

        conn.commit()
        logger.info(
            "Admin deleted user_id=%s (%s) by %s",
            user_id, deleted["username"], admin_payload.get("username"),
        )
        # 204 No Content — return nothing
        return None

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.error("admin_delete_user error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()
