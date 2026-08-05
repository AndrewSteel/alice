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
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import httpx

logger = logging.getLogger("alice-chat-stream.memory")

POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "")
WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "http://weaviate:8080").rstrip("/")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")

WORKING_MEMORY_LIMIT = 20
LONG_TERM_MEMORY_LIMIT = 5

# ---------------------------------------------------------------------------
# Language configuration (PROJ-63)
# ---------------------------------------------------------------------------
# Static, duplicated per container (see alice-auth/main.py for the sibling
# copy). To add a language: append an entry here AND in every other container's
# copy, then redeploy. Only `code` + `llm_instruction` are used here.
LANGUAGES: list[dict[str, str]] = [
    {
        "code": "de",
        "displayName_de": "Deutsch",
        "displayName_en": "German",
        "llm_instruction": "Antworte immer auf Deutsch. Sei präzise und hilfreich.",
    },
    {
        "code": "en",
        "displayName_de": "Englisch",
        "displayName_en": "English",
        "llm_instruction": "Reply in English.",
    },
]

# Legacy word-form aliases still tolerated in case the migration hasn't run yet.
LANGUAGE_ALIASES: dict[str, str] = {
    "deutsch": "de",
    "englisch": "en",
}

_LLM_INSTRUCTION_BY_CODE = {lang["code"]: lang["llm_instruction"] for lang in LANGUAGES}
_DEFAULT_LANGUAGE_CODE = "de"


def _llm_instruction_for(sprache: str | None) -> str:
    """
    Resolve the LLM language instruction for a stored `sprache` value.
    Accepts ISO codes and legacy word-form aliases; unknown/missing values
    fall back to German (PRD constraint "Sprache: primär Deutsch").
    """
    code = sprache if sprache in _LLM_INSTRUCTION_BY_CODE else LANGUAGE_ALIASES.get(sprache or "")
    return _LLM_INSTRUCTION_BY_CODE.get(code, _LLM_INSTRUCTION_BY_CODE[_DEFAULT_LANGUAGE_CODE])

LOCAL_TZ = ZoneInfo("Europe/Berlin")
_WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _current_datetime_line() -> str:
    """Render the current local date/time so the LLM doesn't have to guess it."""
    now = datetime.now(LOCAL_TZ)
    weekday = _WEEKDAYS_DE[now.weekday()]
    return f"Aktuelles Datum und Uhrzeit: {weekday}, {now.strftime('%d.%m.%Y %H:%M')} Uhr."

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
        "- search_images: Durchsucht die Bilder-Sammlung (Ort, Motiv, Aktualität). Ergebnisse "
        "erscheinen immer als Kachel-Raster, auch ohne 'zeige mir' in der Anfrage.",
        "- search_emails: Durchsucht indexierte E-Mails des Nutzers semantisch.",
        "- get_email_body: Lädt den vollständigen Inhalt einer E-Mail (benötigt mailbox_id + uid aus search_emails).",
        "- home_assistant: Steuert Home-Assistant-Geräte direkt (Licht, Heizung, Schalter, ...).",
        "- remember: Speichert dauerhafte Fakten oder Präferenzen über den Nutzer.",
        "- recall: Sucht semantisch in vergangenen Gesprächen.",
        "",
        "Bei search_documents, search_emails und search_images: vom Nutzer genannte konkrete "
        "Begriffe (Firmennamen, Themen, Orte, Motive, Stichworte) unverändert als query/location "
        "übernehmen, nicht paraphrasieren. Bei rein zeitlichen Anfragen ('die letzten...', "
        "'neueste...') sort_mode='recency' setzen statt einen erfundenen Suchtext zu bilden.",
        "",
        "Äußert der Nutzer bei search_documents, search_emails oder search_images einen "
        "ausdrücklichen 'alle zeigen'-Wunsch (z.B. 'alle Rechnungen', 'alle Bilder aus Tokyo'), "
        "frage zuerst nach, ob wirklich alle (potenziell vielen) Treffer gezeigt werden sollen — "
        "rufe das Werkzeug NICHT sofort mit limit=100 auf. Erst nach ausdrücklicher Bestätigung "
        "das Werkzeug mit limit=100 aufrufen; lehnt der Nutzer ab oder nennt stattdessen eine "
        "Zahl, diese Zahl bzw. die Standardanzahl verwenden. Jede neue 'alle'-Anfrage löst erneut "
        "die Rückfrage aus, auch wenn eine frühere bereits bestätigt wurde. Enthält ein "
        "Werkzeugergebnis more_available=true, weise im Antworttext explizit darauf hin, dass es "
        "weitere, nicht angezeigte Treffer gibt.",
        "",
        _current_datetime_line(),
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
    lines.append(_llm_instruction_for(sprache))

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
async def ensure_session(session_id: str, user_id: str, source: str | None = None) -> None:
    """Idempotent insert into alice.sessions; bumps last_activity on hit."""
    await pool().execute(
        """
        INSERT INTO alice.sessions (session_id, user_id, last_activity, message_count, session_type, expires_at, source)
        VALUES ($1::uuid, $2, NOW(), 0, 'ha_only', NOW() + INTERVAL '30 days', $3)
        ON CONFLICT (session_id) DO UPDATE
            SET last_activity = NOW()
        """,
        session_id,
        user_id,
        source,
    )


async def promote_to_llm(session_id: str) -> None:
    """Promote a ha_only session to llm (remove expiry, makes it permanent)."""
    await pool().execute(
        """
        UPDATE alice.sessions
        SET session_type = 'llm', expires_at = NULL
        WHERE session_id = $1::uuid AND session_type = 'ha_only'
        """,
        session_id,
    )


async def insert_user_message(session_id: str, user_id: str, content: str, msg_type: str = "user_text") -> int:
    row = await pool().fetchrow(
        """
        WITH ins AS (
            INSERT INTO alice.messages (session_id, user_id, role, content, msg_type)
            VALUES ($1::uuid, $2, 'user', $3, $4)
            RETURNING id
        ),
        upd AS (
            UPDATE alice.sessions
            SET message_count = message_count + 1, last_activity = NOW()
            WHERE session_id = $1::uuid
        )
        SELECT id FROM ins
        """,
        session_id,
        user_id,
        content,
        msg_type,
    )
    return row["id"]


async def insert_llm_thinking(session_id: str, user_id: str, content: str) -> None:
    """Save accumulated thinking tokens. role='system' keeps them out of LLM context window."""
    if not content:
        return
    await pool().execute(
        """
        INSERT INTO alice.messages (session_id, user_id, role, content, msg_type)
        VALUES ($1::uuid, $2, 'system', $3, 'llm_thinking')
        """,
        session_id,
        user_id,
        content,
    )


async def insert_llm_response(
    session_id: str,
    user_id: str,
    content: str,
    tool_calls: list[dict] | None,
    tool_results: dict | None,
    token_count: int = 0,
) -> int:
    """Insert LLM response and atomically promote session to llm type."""
    row = await pool().fetchrow(
        """
        WITH ins AS (
            INSERT INTO alice.messages
                (session_id, user_id, role, content, tool_calls, tool_results, token_count, msg_type)
            VALUES ($1::uuid, $2, 'assistant', $3, $4::jsonb, $5::jsonb, $6, 'llm_response')
            RETURNING id
        ),
        upd AS (
            UPDATE alice.sessions
            SET message_count = message_count + 1,
                last_activity = NOW(),
                session_type = 'llm',
                expires_at = NULL
            WHERE session_id = $1::uuid
        )
        SELECT id FROM ins
        """,
        session_id,
        user_id,
        content,
        json.dumps(tool_calls) if tool_calls else None,
        json.dumps(tool_results) if tool_results is not None else None,
        token_count,
    )
    return row["id"]


async def insert_ha_result(
    session_id: str,
    user_id: str,
    content: str,
    tool_results: dict | None = None,
) -> None:
    """Save HA fast-path result. Session stays ha_only."""
    await pool().execute(
        """
        WITH ins AS (
            INSERT INTO alice.messages (session_id, user_id, role, content, tool_results, msg_type)
            VALUES ($1::uuid, $2, 'assistant', $3, $4::jsonb, 'ha_result')
        )
        UPDATE alice.sessions
        SET message_count = message_count + 1, last_activity = NOW()
        WHERE session_id = $1::uuid
        """,
        session_id,
        user_id,
        content,
        json.dumps(tool_results) if tool_results is not None else None,
    )


async def count_llm_responses(session_id: str) -> int:
    """Count llm_response messages for session (used to detect first response)."""
    row = await pool().fetchrow(
        """
        SELECT COUNT(*) AS cnt
        FROM alice.messages
        WHERE session_id = $1::uuid AND msg_type = 'llm_response'
        """,
        session_id,
    )
    return int(row["cnt"])


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


async def generate_title_async(session_id: str, user_message: str, llm_response: str) -> None:
    """Background asyncio task: call Ollama to generate a short German title for the session."""
    prompt = (
        f"Erstelle einen sehr kurzen deutschen Titel (max. 60 Zeichen) für dieses Gespräch.\n"
        f"Nutzer: {user_message[:300]}\n"
        f"Assistent: {llm_response[:300]}\n"
        f"Titel (nur der Titel, ohne Anführungszeichen):"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                },
            )
            data = resp.json()
            title = (data.get("response") or "").strip()
            if len(title) > 60:
                title = title[:60].rstrip()
            if title:
                await pool().execute(
                    """
                    UPDATE alice.sessions
                    SET title = $1
                    WHERE session_id = $2::uuid AND title IS NULL
                    """,
                    title,
                    session_id,
                )
                logger.info("Title generated for session %s: %s", session_id, title)
    except Exception as exc:
        logger.warning("Title generation failed for session %s: %s", session_id, exc)
