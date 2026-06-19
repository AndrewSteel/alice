"""
Speaker profile database operations (PROJ-43).

Uses asyncpg to read/write speaker embeddings from alice.users.
The pool is initialised once at startup via init_pool().

Data layout in alice.users:
  speaker_embeddings          JSONB   — [[v1, v2, ...], ...]  (list of float vectors)
  speaker_enrollment_complete BOOLEAN — true once at least one embedding exists
  allow_voice_enrollment      BOOLEAN — admin toggle for WebApp enrollment button
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("alice-speech-gateway.speaker_db")

_pool = None  # asyncpg.Pool


async def init_pool(dsn: str) -> None:
    """Create the asyncpg connection pool. Call once at startup."""
    import asyncpg

    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    logger.info("Speaker DB pool connected")


def is_ready() -> bool:
    return _pool is not None


async def load_all_profiles() -> list[dict]:
    """
    Return all enrolled users as speaker profile dicts.

    Each dict: {"user_id": str, "display_name": str, "embeddings": [[float, ...]]}
    Only users with speaker_enrollment_complete = true and is_active = true are returned.
    """
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id::text AS user_id,
                      COALESCE(display_name, username) AS display_name,
                      speaker_embeddings
               FROM alice.users
               WHERE speaker_enrollment_complete = true
                 AND is_active = true"""
        )
    profiles = []
    for row in rows:
        raw = row["speaker_embeddings"]
        if isinstance(raw, str):
            embeddings = json.loads(raw)
        else:
            embeddings = raw or []
        profiles.append({
            "user_id": row["user_id"],
            "display_name": row["display_name"],
            "embeddings": embeddings,
        })
    return profiles


async def save_embeddings(user_id: str, embeddings: list[list[float]]) -> None:
    """Overwrite all stored voice samples for a user."""
    if _pool is None:
        raise RuntimeError("speaker_db pool not initialised")
    async with _pool.acquire() as conn:
        await conn.execute(
            """UPDATE alice.users
               SET speaker_embeddings          = $1::jsonb,
                   speaker_enrollment_complete = true
               WHERE id = $2::uuid""",
            json.dumps(embeddings),
            user_id,
        )
    logger.info("Saved %d embeddings for user %s", len(embeddings), user_id)


async def delete_embeddings(user_id: str) -> bool:
    """
    Clear voice profile for a user. Returns True if a row was updated.
    """
    if _pool is None:
        raise RuntimeError("speaker_db pool not initialised")
    async with _pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE alice.users
               SET speaker_embeddings          = '[]'::jsonb,
                   speaker_enrollment_complete = false
               WHERE id = $1::uuid""",
            user_id,
        )
    updated = result != "UPDATE 0"
    if updated:
        logger.info("Deleted speaker profile for user %s", user_id)
    return updated


async def list_enrolled_profiles() -> list[dict]:
    """Return summary list of all enrolled users for admin UI."""
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id::text AS user_id,
                      username,
                      COALESCE(display_name, username) AS display_name,
                      role,
                      jsonb_array_length(COALESCE(speaker_embeddings, '[]'::jsonb)) AS sample_count,
                      created_at
               FROM alice.users
               WHERE speaker_enrollment_complete = true
               ORDER BY display_name"""
        )
    return [dict(row) for row in rows]


async def get_user(user_id: str) -> dict | None:
    """Return basic user info. None if not found."""
    if _pool is None:
        return None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id::text AS user_id, username, display_name, role,
                      allow_voice_enrollment
               FROM alice.users WHERE id = $1::uuid""",
            user_id,
        )
    return dict(row) if row else None


async def username_exists(username: str) -> bool:
    """Check whether a username is already taken."""
    if _pool is None:
        return False
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM alice.users WHERE username = $1", username
        )
    return row is not None


async def create_enrolled_user(
    username: str,
    display_name: str,
    anrede: str,
    sprache: str,
    role: str,
    embeddings: list[list[float]],
) -> dict:
    """
    Create a new alice user with voice profile. Initialises default permissions.
    Returns the created user dict.
    """
    if _pool is None:
        raise RuntimeError("speaker_db pool not initialised")
    async with _pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO alice.users
                       (username, display_name, role,
                        speaker_embeddings, speaker_enrollment_complete)
                   VALUES ($1, $2, $3, $4::jsonb, true)
                   RETURNING id::text AS user_id, username, display_name, role""",
                username,
                display_name,
                role,
                json.dumps(embeddings),
            )
            user_id = row["user_id"]
            await conn.execute(
                "SELECT alice.init_user_permissions($1::uuid, $2)",
                user_id,
                role,
            )
            # Persist enrollment preferences (anrede/sprache) so the agent
            # addresses and answers the user as chosen during the dialog.
            await conn.execute(
                """INSERT INTO alice.user_profiles (user_id, preferences)
                   VALUES ($1, $2::jsonb)
                   ON CONFLICT (user_id) DO UPDATE
                       SET preferences  = alice.user_profiles.preferences || EXCLUDED.preferences,
                           last_updated = NOW()""",
                user_id,
                json.dumps({"anrede": anrede, "sprache": sprache}),
            )
    logger.info("Created enrolled user %s (role=%s)", username, role)
    return dict(row)


async def set_allow_voice_enrollment(user_id: str, allow: bool) -> None:
    """Toggle the WebApp enrollment button for a user."""
    if _pool is None:
        raise RuntimeError("speaker_db pool not initialised")
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE alice.users SET allow_voice_enrollment = $1 WHERE id = $2::uuid",
            allow,
            user_id,
        )
