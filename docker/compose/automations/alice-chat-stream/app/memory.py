"""
Three-tier memory:

Tier 1 (Working)   PostgreSQL alice.messages — last 20 messages of session
Tier 2 (Long-term) Weaviate AliceMemory       — semantic recall for past convos
Tier 3 (Profile)   PostgreSQL alice.user_profiles — name, anrede, sprache, ...

Persistence:
  - User message is written to alice.messages BEFORE the stream starts.
  - Assistant message is written AFTER the stream ends (full text + tool_results).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import asyncpg
import httpx

logger = logging.getLogger("alice-chat-stream.memory")

POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "")
WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "http://weaviate:8080").rstrip("/")

WORKING_MEMORY_LIMIT = 20
LONG_TERM_MEMORY_LIMIT = 5

_pool: asyncpg.Pool | None = None


# ---------------------------------------------------------------------------
# Connection pool lifecycle (called from FastAPI lifespan)
# ---------------------------------------------------------------------------
async def init_pool() -> None:
    global _pool
    if not POSTGRES_DSN:
        raise RuntimeError("POSTGRES_DSN is not set")
    _pool = await asyncpg.create_pool(
        dsn=POSTGRES_DSN,
        min_size=2,
        max_size=10,
        command_timeout=10,
    )
    logger.info("PostgreSQL pool ready")


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PG pool not initialised")
    return _pool


async def healthy() -> bool:
    if _pool is None:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("PG health check failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Tier 1: Working memory
# ---------------------------------------------------------------------------
async def load_working_memory(session_id: str, limit: int = WORKING_MEMORY_LIMIT) -> list[dict]:
    """
    Return the last `limit` messages of the session in chronological order.
    Each message is a dict {role, content}. Tool messages are ignored — the
    LLM does not need to see them on resume.
    """
    rows = await pool().fetch(
        """
        SELECT role, content
        FROM alice.messages
        WHERE session_id = $1::uuid
          AND role IN ('user', 'assistant')
        ORDER BY timestamp DESC
        LIMIT $2
        """,
        session_id,
        limit,
    )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Tier 3: User profile
# ---------------------------------------------------------------------------
async def load_user_profile(user_id: str) -> dict[str, Any]:
    row = await pool().fetchrow(
        """
        SELECT facts, preferences
        FROM alice.user_profiles
        WHERE user_id = $1
        """,
        user_id,
    )
    if not row:
        return {"facts": {}, "preferences": {}}

    facts = row["facts"] or {}
    preferences = row["preferences"] or {}
    if isinstance(facts, str):
        facts = json.loads(facts)
    if isinstance(preferences, str):
        preferences = json.loads(preferences)
    return {"facts": dict(facts), "preferences": dict(preferences)}


def build_system_prompt(
    profile: dict[str, Any],
    long_term_memories: list[dict] | None = None,
) -> str:
    """
    Build the system prompt that goes to Ollama. Injects the user profile
    so Alice knows the user's name, salutation, language, and interests.
    Optionally injects relevant long-term memories (Tier 2).
    """
    facts = profile.get("facts") or {}
    prefs = profile.get("preferences") or {}

    name = facts.get("name") or ""
    interests = facts.get("interessen") or []
    anrede = prefs.get("anrede") or "du"
    sprache = prefs.get("sprache") or "deutsch"
    detailgrad = prefs.get("detailgrad") or "normal"

    lines = [
        "Du bist Alice, ein persönlicher Assistent und Smart-Home-Controller.",
        "",
        "Du hast Zugriff auf folgende Tools:",
        "- search_documents: Durchsucht das Dokumentenarchiv (Rechnungen, Kontoauszüge, BankTransactions, Verträge, E-Mails, Wertpapierabrechnungen). "
        "Für Fragen nach konkreten Zahlungen/Buchungen doc_type='BankTransaction' verwenden.",
        "- get_document_details: Holt alle Details zu einem Dokument per weaviate_id + collection.",
        "- home_assistant: Steuert Home-Assistant-Geräte direkt (Licht, Heizung, Schalter, ...).",
        "- remember: Speichert dauerhafte Fakten oder Präferenzen über den Nutzer.",
        "- recall: Sucht semantisch in vergangenen Gesprächen.",
        "",
    ]

    if name:
        lines.append(f"Der Nutzer heißt {name}.")
    if anrede == "sie":
        lines.append("Sprich den Nutzer mit „Sie“ an.")
    else:
        lines.append("Sprich den Nutzer mit „du“ an.")
    if interests:
        lines.append("Interessen des Nutzers: " + ", ".join(interests) + ".")
    if detailgrad and detailgrad != "normal":
        lines.append(f"Detailgrad der Antworten: {detailgrad}.")
    if sprache == "englisch":
        lines.append("Reply in English.")
    else:
        lines.append("Antworte immer auf Deutsch. Sei präzise und hilfreich.")

    if long_term_memories:
        lines.append("")
        lines.append("### Relevante Erinnerungen aus früheren Gesprächen")
        for m in long_term_memories:
            content = (m.get("content") or "").strip()
            if content:
                lines.append(f"- {content}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tier 2: Long-term memory (Weaviate)
# ---------------------------------------------------------------------------
async def recall_long_term(
    user_id: str,
    query: str,
    limit: int = LONG_TERM_MEMORY_LIMIT,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """
    nearText search on AliceMemory. Returns a list of {content, role,
    timestamp, certainty}. Errors are swallowed and an empty list is
    returned — long-term memory is best-effort, never blocks the chat.
    """
    if not query.strip():
        return []

    safe_query = (
        query.replace("\\", "\\\\")
        .replace('"', "'")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("\t", " ")
    )[:500]
    safe_user = user_id.replace('"', "'")

    gql = (
        '{ Get { AliceMemory('
        f'nearText: {{ concepts: ["{safe_query}"] }} '
        f'where: {{ path: ["userId"], operator: Equal, valueText: "{safe_user}" }} '
        f'limit: {int(limit)}'
        ') { content role timestamp _additional { certainty } } } }'
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{WEAVIATE_URL}/v1/graphql",
                json={"query": gql},
                headers={"Content-Type": "application/json"},
            )
            data = resp.json()
            items = (
                data.get("data", {})
                .get("Get", {})
                .get("AliceMemory", [])
                or []
            )
            return [
                {
                    "content": it.get("content") or "",
                    "role": it.get("role") or "",
                    "timestamp": it.get("timestamp"),
                    "certainty": (it.get("_additional") or {}).get("certainty", 0.0),
                }
                for it in items
            ]
    except Exception as exc:
        logger.warning("Weaviate recall failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
async def ensure_session(session_id: str, user_id: str) -> None:
    """Idempotent insert into alice.sessions; bumps last_activity on hit."""
    await pool().execute(
        """
        INSERT INTO alice.sessions (session_id, user_id, last_activity, message_count)
        VALUES ($1::uuid, $2, NOW(), 0)
        ON CONFLICT (session_id) DO UPDATE
            SET last_activity = NOW()
        """,
        session_id,
        user_id,
    )


async def insert_user_message(session_id: str, user_id: str, content: str) -> int:
    row = await pool().fetchrow(
        """
        INSERT INTO alice.messages (session_id, user_id, role, content)
        VALUES ($1::uuid, $2, 'user', $3)
        RETURNING id
        """,
        session_id,
        user_id,
        content,
    )
    await pool().execute(
        """
        UPDATE alice.sessions
        SET message_count = message_count + 1, last_activity = NOW()
        WHERE session_id = $1::uuid
        """,
        session_id,
    )
    return row["id"]


async def insert_assistant_message(
    session_id: str,
    user_id: str,
    content: str,
    tool_calls: list[dict] | None,
    tool_results: dict | None,
    token_count: int = 0,
) -> int:
    row = await pool().fetchrow(
        """
        INSERT INTO alice.messages
            (session_id, user_id, role, content, tool_calls, tool_results, token_count)
        VALUES ($1::uuid, $2, 'assistant', $3, $4::jsonb, $5::jsonb, $6)
        RETURNING id
        """,
        session_id,
        user_id,
        content,
        json.dumps(tool_calls) if tool_calls else None,
        json.dumps(tool_results) if tool_results is not None else None,
        token_count,
    )
    await pool().execute(
        """
        UPDATE alice.sessions
        SET message_count = message_count + 1, last_activity = NOW()
        WHERE session_id = $1::uuid
        """,
        session_id,
    )
    return row["id"]


async def upsert_profile_fact(user_id: str, key: str, value: Any) -> None:
    """remember-tool implementation: write a single fact into alice.user_profiles.facts."""
    await pool().execute(
        """
        INSERT INTO alice.user_profiles (user_id, facts, preferences, last_updated)
        VALUES ($1, jsonb_build_object($2::text, $3::jsonb), '{}'::jsonb, NOW())
        ON CONFLICT (user_id) DO UPDATE
            SET facts = COALESCE(alice.user_profiles.facts, '{}'::jsonb)
                        || jsonb_build_object($2::text, $3::jsonb),
                last_updated = NOW()
        """,
        user_id,
        key,
        json.dumps(value),
    )
