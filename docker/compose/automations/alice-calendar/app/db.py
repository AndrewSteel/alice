"""
PostgreSQL access for alice-calendar (asyncpg).

Only selection metadata lives here (alice.calendar_selections) — never event
data. Every query is scoped by the caller's user_id.
"""
from __future__ import annotations

import json
import logging
import os

import asyncpg

logger = logging.getLogger("alice-calendar.db")

POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "")
ROLES = ("admin", "user", "guest", "child")

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    if not POSTGRES_DSN:
        raise RuntimeError("POSTGRES_DSN is not set")
    _pool = await asyncpg.create_pool(dsn=POSTGRES_DSN, min_size=1, max_size=5)


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised")
    return _pool


async def healthy() -> bool:
    try:
        await pool().fetchval("SELECT 1")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Permission + user settings
# ---------------------------------------------------------------------------
async def can_use_calendar(user_id: str) -> bool:
    """Fresh per request — a revoked role locks chat and tab immediately."""
    row = await pool().fetchrow(
        """
        SELECT pa.can_use_calendar, u.is_active
        FROM alice.users u
        LEFT JOIN alice.permissions_assistant pa ON pa.user_id = u.id
        WHERE u.id = $1::uuid
        """,
        user_id,
    )
    return bool(row and row["is_active"] and row["can_use_calendar"])


async def user_timezone(user_id: str) -> str | None:
    """Optional per-user zone from user_profiles.preferences.timezone."""
    try:
        return await pool().fetchval(
            "SELECT preferences->>'timezone' FROM alice.user_profiles WHERE user_id = $1::uuid",
            user_id,
        )
    except Exception as exc:
        logger.debug("timezone lookup failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Calendar selection
# ---------------------------------------------------------------------------
async def list_selections(user_id: str) -> list[dict]:
    rows = await pool().fetch(
        """
        SELECT connection_id::text, calendar_id, is_active, is_default
        FROM alice.calendar_selections
        WHERE user_id = $1::uuid
        ORDER BY created_at
        LIMIT 500
        """,
        user_id,
    )
    return [dict(r) for r in rows]


async def delete_selections(user_id: str, connection_id: str, calendar_ids: list[str]) -> None:
    """Remove stale rows (calendar deleted in Google / access withdrawn)."""
    if not calendar_ids:
        return
    await pool().execute(
        """
        DELETE FROM alice.calendar_selections
        WHERE user_id = $1::uuid AND connection_id = $2::uuid AND calendar_id = ANY($3::text[])
        """,
        user_id, connection_id, calendar_ids,
    )


async def set_selection(
    user_id: str,
    connection_id: str,
    calendar_id: str,
    is_active: bool | None,
    is_default: bool | None,
    writable: bool,
) -> None:
    """Apply a tab toggle with the spec rules, atomically.

    - activating a writable calendar while the user has no default makes it
      the default (covers "first calendar" even if a read-only one was
      activated before)
    - default only for active, writable calendars; unique per user
    - deactivating the default removes the default (no automatic successor)
    """
    async with pool().acquire() as conn:
        async with conn.transaction():
            # Serialise concurrent toggles of the same user.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"calsel:{user_id}")
            row = await conn.fetchrow(
                """
                SELECT is_active, is_default FROM alice.calendar_selections
                WHERE connection_id = $1::uuid AND calendar_id = $2 AND user_id = $3::uuid
                """,
                connection_id, calendar_id, user_id,
            )
            active = row["is_active"] if row else False
            default = row["is_default"] if row else False

            if is_active is not None:
                if is_active and not active:
                    has_default = await conn.fetchval(
                        "SELECT EXISTS (SELECT 1 FROM alice.calendar_selections "
                        "WHERE user_id = $1::uuid AND is_default)",
                        user_id,
                    )
                    if not has_default and writable and is_default is None:
                        is_default = True
                active = is_active
                if not active:
                    default = False

            if is_default is not None:
                if is_default:
                    if not active:
                        raise ValueError("Nur aktive Kalender können Standard sein")
                    if not writable:
                        raise ValueError("Schreibgeschützte Kalender können nicht Standard sein")
                    await conn.execute(
                        "UPDATE alice.calendar_selections SET is_default = FALSE "
                        "WHERE user_id = $1::uuid AND is_default",
                        user_id,
                    )
                default = is_default

            if not active and not default:
                # Inactive rows carry no information — keep the table minimal.
                await conn.execute(
                    "DELETE FROM alice.calendar_selections "
                    "WHERE connection_id = $1::uuid AND calendar_id = $2 AND user_id = $3::uuid",
                    connection_id, calendar_id, user_id,
                )
                return

            await conn.execute(
                """
                INSERT INTO alice.calendar_selections
                    (connection_id, user_id, calendar_id, is_active, is_default)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5)
                ON CONFLICT (connection_id, calendar_id)
                DO UPDATE SET is_active = EXCLUDED.is_active, is_default = EXCLUDED.is_default
                """,
                connection_id, user_id, calendar_id, active, default,
            )


async def clear_default(user_id: str, connection_id: str, calendar_id: str) -> None:
    """A calendar turned read-only in Google can no longer be the default."""
    await pool().execute(
        """
        UPDATE alice.calendar_selections SET is_default = FALSE
        WHERE user_id = $1::uuid AND connection_id = $2::uuid AND calendar_id = $3
        """,
        user_id, connection_id, calendar_id,
    )


# ---------------------------------------------------------------------------
# Role config (admin)
# ---------------------------------------------------------------------------
async def get_role_config() -> list[dict]:
    rows = await pool().fetch(
        "SELECT role, assistant_permissions FROM alice.role_templates ORDER BY role"
    )
    out = []
    for r in rows:
        ap = r["assistant_permissions"]
        if isinstance(ap, str):
            ap = json.loads(ap)
        out.append({"role": r["role"], "can_use_calendar": bool((ap or {}).get("can_use_calendar", False))})
    return out


async def set_role_config(roles: list[dict]) -> None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            for rc in roles:
                await conn.execute(
                    "UPDATE alice.role_templates "
                    "SET assistant_permissions = assistant_permissions || $2::jsonb "
                    "WHERE role = $1",
                    rc["role"], json.dumps({"can_use_calendar": rc["can_use_calendar"]}),
                )
                # Keep the per-user flag in step (same pattern as PROJ-85 timers).
                await conn.execute(
                    "UPDATE alice.permissions_assistant pa "
                    "SET can_use_calendar = $2, updated_at = NOW() "
                    "FROM alice.users u WHERE pa.user_id = u.id AND u.role = $1",
                    rc["role"], rc["can_use_calendar"],
                )
