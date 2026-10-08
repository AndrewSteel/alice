"""
PostgreSQL access for alice-lists (asyncpg).

Visibility is enforced in every query: a user sees shared lists plus the
private lists he owns — nobody else's, admin included. The unknown speaker
(no user) never reaches the item queries except for the shopping list.
"""
from __future__ import annotations

import json
import logging
import os

import asyncpg

logger = logging.getLogger("alice-lists.db")

POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "")
ROLES = ("admin", "user", "guest", "child")
MY_TASKS = "Meine Aufgaben"
ITEM_FETCH_LIMIT = 5000
LIST_FETCH_LIMIT = 500

_pool: asyncpg.Pool | None = None

_LIST_COLS = "l.id::text AS id, l.name, l.is_shared, l.owner_id::text AS owner_id, " \
             "l.created_by::text AS created_by, l.is_shopping"
_ITEM_COLS = "i.id::text AS id, i.list_id::text AS list_id, i.title, i.note, i.due_at, i.due_has_time, " \
             "i.deadline_at, i.deadline_has_time, i.priority, i.is_done, i.done_at, " \
             "i.done_by::text AS done_by, i.created_at, i.updated_at"


class DuplicateName(Exception):
    """A visible list already carries this name."""


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
# Caller + settings
# ---------------------------------------------------------------------------
async def caller_access(user_id: str) -> tuple[str | None, bool]:
    """(role, can_use_lists), read fresh per request — the gateway JWT always
    claims "user" and a revoked role must lock immediately."""
    row = await pool().fetchrow(
        """
        SELECT u.role, u.is_active, pa.can_use_lists
        FROM alice.users u
        LEFT JOIN alice.permissions_assistant pa ON pa.user_id = u.id
        WHERE u.id = $1::uuid
        """,
        user_id,
    )
    if not row or not row["is_active"]:
        return None, False
    return row["role"], bool(row["can_use_lists"])


async def user_timezone(user_id: str) -> str | None:
    try:
        return await pool().fetchval(
            "SELECT preferences->>'timezone' FROM alice.user_profiles WHERE user_id = $1::uuid",
            user_id,
        )
    except Exception as exc:
        logger.debug("timezone lookup failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------
async def visible_lists(user_id: str | None) -> list[dict]:
    """Shared lists + the caller's private lists, with open item counts.
    user_id None (unknown speaker) → only the shopping list."""
    rows = await pool().fetch(
        f"""
        SELECT {_LIST_COLS},
               COUNT(i.id) FILTER (WHERE NOT i.is_done) AS open_count,
               COUNT(i.id) FILTER (WHERE i.is_done) AS done_count
        FROM alice.lists l
        LEFT JOIN alice.list_items i ON i.list_id = l.id
        WHERE ($1::uuid IS NULL AND l.is_shopping)
           OR ($1::uuid IS NOT NULL AND (l.is_shared OR l.owner_id = $1::uuid))
        GROUP BY l.id
        ORDER BY l.is_shared, lower(l.name)
        LIMIT {LIST_FETCH_LIMIT}
        """,
        user_id,
    )
    return [dict(r) for r in rows]


async def default_list_id(user_id: str) -> str | None:
    return await pool().fetchval(
        "SELECT default_list_id::text FROM alice.list_preferences WHERE user_id = $1::uuid", user_id,
    )


async def ensure_default_list(user_id: str) -> str:
    """The user's default list id. A missing or vanished default falls back to
    the private "Meine Aufgaben", created on demand (spec)."""
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"lists:default:{user_id}")
            current = await conn.fetchval(
                """
                SELECT p.default_list_id::text FROM alice.list_preferences p
                JOIN alice.lists l ON l.id = p.default_list_id
                WHERE p.user_id = $1::uuid AND (l.is_shared OR l.owner_id = $1::uuid)
                """,
                user_id,
            )
            if current:
                return current
            list_id = await conn.fetchval(
                "SELECT id::text FROM alice.lists WHERE NOT is_shared AND owner_id = $1::uuid "
                "AND lower(btrim(name)) = lower($2)",
                user_id, MY_TASKS,
            )
            if not list_id:
                list_id = await conn.fetchval(
                    "INSERT INTO alice.lists (name, is_shared, owner_id, created_by) "
                    "VALUES ($2, FALSE, $1::uuid, $1::uuid) RETURNING id::text",
                    user_id, MY_TASKS,
                )
            await _set_default(conn, user_id, list_id)
            return list_id


async def _set_default(conn, user_id: str, list_id: str) -> None:
    await conn.execute(
        """
        INSERT INTO alice.list_preferences (user_id, default_list_id) VALUES ($1::uuid, $2::uuid)
        ON CONFLICT (user_id) DO UPDATE SET default_list_id = EXCLUDED.default_list_id, updated_at = NOW()
        """,
        user_id, list_id,
    )


async def set_default(user_id: str, list_id: str) -> None:
    async with pool().acquire() as conn:
        await _set_default(conn, user_id, list_id)


async def create_list(user_id: str, name: str, shared: bool) -> dict:
    """Insert a list. Visible-name uniqueness (case-insensitive) is checked
    here under a lock; the DB indexes back it per scope."""
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext('lists:names'))")
            clash = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM alice.lists WHERE lower(btrim(name)) = lower(btrim($2)) "
                "AND (is_shared OR owner_id = $1::uuid))",
                user_id, name,
            )
            if clash:
                raise DuplicateName(name)
            try:
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO alice.lists AS l (name, is_shared, owner_id, created_by)
                    VALUES (btrim($2), $3, CASE WHEN $3 THEN NULL ELSE $1::uuid END, $1::uuid)
                    RETURNING {_LIST_COLS}
                    """,
                    user_id, name, shared,
                )
            except asyncpg.UniqueViolationError:
                raise DuplicateName(name)
    return dict(row)


async def rename_list(user_id: str, list_id: str, new_name: str) -> dict | None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext('lists:names'))")
            clash = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM alice.lists WHERE lower(btrim(name)) = lower(btrim($2)) "
                "AND id <> $3::uuid AND (is_shared OR owner_id = $1::uuid))",
                user_id, new_name, list_id,
            )
            if clash:
                raise DuplicateName(new_name)
            try:
                row = await conn.fetchrow(
                    f"UPDATE alice.lists l SET name = btrim($2) WHERE id = $1::uuid RETURNING {_LIST_COLS}",
                    list_id, new_name,
                )
            except asyncpg.UniqueViolationError:
                raise DuplicateName(new_name)
    return dict(row) if row else None


async def get_list(list_id: str) -> dict | None:
    row = await pool().fetchrow(
        f"""
        SELECT {_LIST_COLS}, COUNT(i.id) AS item_count
        FROM alice.lists l LEFT JOIN alice.list_items i ON i.list_id = l.id
        WHERE l.id = $1::uuid GROUP BY l.id
        """,
        list_id,
    )
    return dict(row) if row else None


async def delete_list(list_id: str) -> bool:
    return await pool().fetchval(
        "WITH d AS (DELETE FROM alice.lists WHERE id = $1::uuid RETURNING 1) SELECT COUNT(*) > 0 FROM d",
        list_id,
    )


async def flag_shopping(list_id: str) -> str | None:
    """Move the shopping flag to `list_id`; returns the previous list's name."""
    async with pool().acquire() as conn:
        async with conn.transaction():
            previous = await conn.fetchval(
                "SELECT name FROM alice.lists WHERE is_shopping AND id <> $1::uuid FOR UPDATE", list_id,
            )
            await conn.execute("UPDATE alice.lists SET is_shopping = FALSE WHERE is_shopping AND id <> $1::uuid",
                               list_id)
            await conn.execute("UPDATE alice.lists SET is_shopping = TRUE WHERE id = $1::uuid AND is_shared",
                               list_id)
    return previous


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
async def fetch_items(list_ids: list[str], done: bool, done_since=None) -> list[dict]:
    if not list_ids:
        return []
    rows = await pool().fetch(
        f"""
        SELECT {_ITEM_COLS} FROM alice.list_items i
        WHERE i.list_id = ANY($1::uuid[]) AND i.is_done = $2
          AND ($3::timestamptz IS NULL OR i.done_at >= $3)
        ORDER BY i.created_at
        LIMIT {ITEM_FETCH_LIMIT}
        """,
        list_ids, done, done_since,
    )
    return [dict(r) for r in rows]


async def get_item(item_id: str) -> dict | None:
    row = await pool().fetchrow(f"SELECT {_ITEM_COLS} FROM alice.list_items i WHERE i.id = $1::uuid", item_id)
    return dict(row) if row else None


async def insert_items(list_id: str, titles: list[str], fields: dict, created_by: str | None) -> list[dict]:
    async with pool().acquire() as conn:
        async with conn.transaction():
            out = []
            for title in titles:
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO alice.list_items AS i (list_id, title, note, due_at, due_has_time,
                        deadline_at, deadline_has_time, priority, created_by)
                    VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9::uuid)
                    RETURNING {_ITEM_COLS}
                    """,
                    list_id, title, fields.get("note"), fields.get("due_at"), bool(fields.get("due_has_time")),
                    fields.get("deadline_at"), bool(fields.get("deadline_has_time")),
                    fields.get("priority") or "normal", created_by,
                )
                out.append(dict(row))
    return out


async def set_done(item_id: str, done: bool, user_id: str | None) -> dict | None:
    """Flip the done state. None when the item is gone or already in that state
    (a concurrent second action — reported, not an error)."""
    row = await pool().fetchrow(
        f"""
        UPDATE alice.list_items i
        SET is_done = $2,
            done_at = CASE WHEN $2 THEN NOW() ELSE NULL END,
            done_by = CASE WHEN $2 THEN $3::uuid ELSE NULL END
        WHERE i.id = $1::uuid AND i.is_done <> $2
        RETURNING {_ITEM_COLS}
        """,
        item_id, done, user_id,
    )
    return dict(row) if row else None


_UPDATABLE = ("title", "note", "due_at", "due_has_time", "deadline_at", "deadline_has_time", "priority",
              "list_id")


async def update_item(item_id: str, changes: dict) -> dict | None:
    sets, args = [], [item_id]
    for key in _UPDATABLE:
        if key in changes:
            args.append(changes[key])
            cast = "::uuid" if key == "list_id" else ""
            sets.append(f"{key} = ${len(args)}{cast}")
    if not sets:
        return await get_item(item_id)
    row = await pool().fetchrow(
        f"UPDATE alice.list_items i SET {', '.join(sets)} WHERE i.id = $1::uuid RETURNING {_ITEM_COLS}",
        *args,
    )
    return dict(row) if row else None


async def delete_items(item_ids: list[str]) -> list[str]:
    rows = await pool().fetch(
        "DELETE FROM alice.list_items WHERE id = ANY($1::uuid[]) RETURNING id::text", item_ids,
    )
    return [r["id"] for r in rows]


async def delete_item_if_unchanged(item_id: str, updated_at) -> str:
    """'deleted' | 'gone' | 'changed' — never deletes a changed entry."""
    async with pool().acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchval(
                "SELECT updated_at FROM alice.list_items WHERE id = $1::uuid FOR UPDATE", item_id,
            )
            if current is None:
                return "gone"
            if current != updated_at:
                return "changed"
            await conn.execute("DELETE FROM alice.list_items WHERE id = $1::uuid", item_id)
    return "deleted"


async def delete_done(list_id: str) -> int:
    return await pool().fetchval(
        "WITH d AS (DELETE FROM alice.list_items WHERE list_id = $1::uuid AND is_done RETURNING 1) "
        "SELECT COUNT(*) FROM d",
        list_id,
    )


async def purge_done(days: int = 30) -> int:
    """Daily cleanup: done items are removed for good after `days`."""
    return await pool().fetchval(
        "WITH d AS (DELETE FROM alice.list_items WHERE is_done AND done_at < NOW() - make_interval(days => $1) "
        "RETURNING 1) SELECT COUNT(*) FROM d",
        days,
    )


# ---------------------------------------------------------------------------
# Role config (admin)
# ---------------------------------------------------------------------------
async def get_role_config() -> list[dict]:
    rows = await pool().fetch("SELECT role, assistant_permissions FROM alice.role_templates ORDER BY role")
    out = []
    for r in rows:
        ap = r["assistant_permissions"]
        if isinstance(ap, str):
            ap = json.loads(ap)
        out.append({"role": r["role"], "can_use_lists": bool((ap or {}).get("can_use_lists", False))})
    return out


async def set_role_config(roles: list[dict]) -> None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            for rc in roles:
                await conn.execute(
                    "UPDATE alice.role_templates "
                    "SET assistant_permissions = assistant_permissions || $2::jsonb WHERE role = $1",
                    rc["role"], json.dumps({"can_use_lists": rc["can_use_lists"]}),
                )
                # Keep the per-user flag in step (same pattern as PROJ-85/87).
                await conn.execute(
                    "UPDATE alice.permissions_assistant pa SET can_use_lists = $2, updated_at = NOW() "
                    "FROM alice.users u WHERE pa.user_id = u.id AND u.role = $1",
                    rc["role"], rc["can_use_lists"],
                )
