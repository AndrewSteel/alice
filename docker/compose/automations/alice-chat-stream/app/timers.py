"""
PROJ-85 — Timer-Agent.

Alice's own timer mechanism. HA's Assist timers are unreachable from the
"Hey Jarvis" path (no entity, no REST service), so Alice counts, names and
notifies herself.

This module holds:
  * text parsing  — duration / absolute time / name / delta from the spoken part
  * role + limit resolution   — per-role permission and caps from role_templates
  * DB operations              — create / extend / shorten / query / pause /
                                 resume / delete, each an atomic, row-locked
                                 status transition (spec "Nebenläufigkeit")

The HA_FAST router (ha_path.decide_path) recognises a timer intent by its
`domain == "timer"` marker and hands the part to `handle_timer_part` here
instead of calling Home Assistant. No LLM, < 200 ms budget — the extra
queries (role, limits, existing timers) are small and indexed.

The background expiry watcher lives in `timer_scheduler.py`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger("alice-chat-stream.timers")

LOCAL_TZ = ZoneInfo("Europe/Berlin")

# Rollen-unabhängige Untergrenze (spec).
MIN_DURATION_SECONDS = 10

# Fallback limits when a role template carries no timer keys (should not
# happen after migration 069, but keeps the handler safe).
_FALLBACK_MAX_ACTIVE = 10
_FALLBACK_MAX_DURATION = 86400

ACTIVE_STATUSES = ("running", "paused")

# German ordinals for collision fallback names ("zweiter 20 Minuten Timer").
_ORDINALS = [
    "zweiter", "dritter", "vierter", "fünfter", "sechster", "siebter",
    "achter", "neunter", "zehnter",
]


# ---------------------------------------------------------------------------
# Text parsing
# ---------------------------------------------------------------------------
@dataclass
class ParsedTime:
    """Result of parsing a duration or absolute time out of a spoken part."""

    seconds: int | None = None          # total duration in seconds
    spoken_duration: str | None = None  # "20 Minuten", "1 Stunde 30 Minuten"
    clock: str | None = None            # "15 Uhr 40" if an absolute time was given
    is_clock: bool = False
    # A time phrase was present but is not a valid timer duration ("3 Wochen").
    rejected: bool = False


def _fmt_duration(total_seconds: int) -> str:
    """Render seconds as a natural German phrase.

    3600 -> "1 Stunde", 5400 -> "1 Stunde 30 Minuten", 150 -> "2 Minuten 30 Sekunden",
    45 -> "45 Sekunden".
    """
    total_seconds = max(0, int(round(total_seconds)))
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h} Stunde" + ("" if h == 1 else "n"))
    if m:
        parts.append(f"{m} Minute" + ("" if m == 1 else "n"))
    if s and not h:  # drop seconds once we're into the hours range
        parts.append(f"{s} Sekunde" + ("" if s == 1 else "n"))
    if not parts:
        return "0 Sekunden"
    return " ".join(parts)


def _fmt_remaining(total_seconds: int) -> str:
    """Shorter phrasing for a remaining time ('noch 3 Minuten', 'noch 45 Sekunden')."""
    total_seconds = max(0, int(round(total_seconds)))
    if total_seconds < 60:
        return f"{total_seconds} Sekunde" + ("" if total_seconds == 1 else "n")
    if total_seconds < 3600:
        m = int(round(total_seconds / 60))
        return f"{m} Minute" + ("" if m == 1 else "n")
    h, rem = divmod(total_seconds, 3600)
    m = rem // 60
    if m:
        return f"{h} Stunde" + ("" if h == 1 else "n") + f" {m} Minute" + ("" if m == 1 else "n")
    return f"{h} Stunde" + ("" if h == 1 else "n")


_UNIT_SECONDS = {
    "sekunde": 1, "sekunden": 1, "sek": 1,
    "minute": 60, "minuten": 60, "min": 60,
    "stunde": 3600, "stunden": 3600, "std": 3600,
}

# "1 Stunde 30 Minuten", "20 Minuten", "2,5 Minuten", "90 sekunden"
_DURATION_TOKEN_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(stunden?|std|minuten?|min|sekunden?|sek)\b",
    re.IGNORECASE,
)
# "15 Uhr 40", "15 Uhr", "4 uhr"
_CLOCK_RE = re.compile(r"\b(\d{1,2})\s*uhr(?:\s*(\d{1,2}))?\b", re.IGNORECASE)


def parse_time(part: str, *, now: datetime | None = None) -> ParsedTime:
    """Parse a duration or an absolute clock time out of a spoken command part.

    Precedence: an explicit duration ("… Minuten/Stunden/Sekunden") wins over a
    bare "X Uhr" reading, so "Timer auf 20 Minuten" is never misread as a clock.
    """
    now = now or datetime.now(LOCAL_TZ)

    duration_tokens = _DURATION_TOKEN_RE.findall(part)
    if duration_tokens:
        total = 0.0
        for value, unit in duration_tokens:
            total += float(value.replace(",", ".")) * _UNIT_SECONDS[unit.lower()]
        seconds = int(round(total))
        return ParsedTime(
            seconds=seconds,
            spoken_duration=_spoken_from_tokens(duration_tokens),
            is_clock=False,
        )

    m = _CLOCK_RE.search(part)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2)) if m.group(2) is not None else 0
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            # spec: exactly "now" counts as already past -> tomorrow.
            if target <= now:
                target = target + timedelta(days=1)
            seconds = int((target - now).total_seconds())
            clock = f"{hh} Uhr" + (f" {mm:02d}" if mm else "")
            return ParsedTime(
                seconds=seconds, spoken_duration=_fmt_duration(seconds),
                clock=clock, is_clock=True,
            )

    # An out-of-range unit ("3 Wochen", "2 Tage", "ein Jahr") is a real time
    # phrase Alice cannot make a timer from — reject it explicitly rather than
    # let the bare-number fallback below misread "3" as 3 minutes
    # (PROJ-85 QA BUG-2).
    if re.search(r"\d+\s*(wochen?|tage?n?|monate?n?|jahre?n?)\b", part, re.IGNORECASE):
        return ParsedTime(rejected=True)

    # Bare number, no unit, no "Uhr" — the sentence splitter leaves the first
    # half of "… auf 10 und einen auf 20 Minuten" as "… auf 10". Read a lone
    # "auf <n>" (or a whole part that is just a number) as minutes.
    bare = re.search(r"\bauf\s+(\d{1,3})\s*$", part.strip(), re.IGNORECASE) or \
        re.fullmatch(r"\s*(\d{1,3})\s*", part)
    if bare:
        minutes = int(bare.group(1))
        if 1 <= minutes <= 999:
            seconds = minutes * 60
            return ParsedTime(
                seconds=seconds, spoken_duration=_fmt_duration(seconds),
                is_clock=False,
            )

    return ParsedTime()


def _spoken_from_tokens(tokens: list[tuple[str, str]]) -> str:
    """Re-render the duration the way it was spoken, normalising the unit word.

    '2,5 minuten' -> '2 Minuten 30 Sekunden' (spec edge case: interpret, don't
    reject); whole values keep their spelling ('1 stunde 30 min' ->
    '1 Stunde 30 Minuten').
    """
    total = 0.0
    for value, unit in tokens:
        total += float(value.replace(",", ".")) * _UNIT_SECONDS[unit.lower()]
    return _fmt_duration(int(round(total)))


_DELTA_RE = re.compile(
    r"um\s+(\d+(?:[.,]\d+)?)\s*(stunden?|std|minuten?|min|sekunden?|sek)\b",
    re.IGNORECASE,
)


def parse_delta(part: str) -> int | None:
    """Parse an "um X Minuten" change delta into seconds. None if absent."""
    m = _DELTA_RE.search(part)
    if not m:
        # bare "… 5 Minuten später/früher"
        m2 = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(stunden?|std|minuten?|min|sekunden?|sek)\b",
            part, re.IGNORECASE,
        )
        if not m2:
            return None
        value, unit = m2.group(1), m2.group(2)
    else:
        value, unit = m.group(1), m.group(2)
    return int(round(float(value.replace(",", ".")) * _UNIT_SECONDS[unit.lower()]))


# "für Kartoffeln", "für den Tee", "für die Nudeln", "namens Kartoffel"
_NAME_RE = re.compile(
    r"\bf[üu]r\s+(?:den|die|das|meine[rn]?|einen?)?\s*([A-Za-zÄÖÜäöüß][\wÄÖÜäöüß-]*)",
    re.IGNORECASE,
)
# German compound noun: "Eiertimer", "Kartoffeltimer" — one word, at least two
# letters before "timer" so a bare "Timer" alone never matches (live QA
# finding 2026-09-17: "Setze einen Eiertimer auf 3 Minuten" is the natural way
# to say this, more common in speech than "Timer für Eier"). The optional
# hyphen accounts for Whisper's actual transcription: it renders this compound
# as "Eier-Timer", not "Eiertimer" (found live 2026-09-17 in gateway logs).
_COMPOUND_NAME_RE = re.compile(
    r"\b([A-Za-zÄÖÜäöüß]{2,}?)-?timer\b", re.IGNORECASE
)
# Reference in a change/query/delete: "den Kartoffel Timer", "der Nudel Timer",
# and derived names "den 20 Minuten Timer", "den 15 Uhr 40 Timer" (first char
# may be a digit — PROJ-85 QA BUG-1).
_REF_NAME_RE = re.compile(
    r"\b(?:den|der|des|dem)\s+([0-9A-Za-zÄÖÜäöüß][\wÄÖÜäöüß -]*?)\s+timer\b",
    re.IGNORECASE,
)
# Reference as a German compound: "den Eiertimer", "der Kartoffeltimer", and
# Whisper's actual "der Eier-Timer" rendering (see _COMPOUND_NAME_RE above).
_REF_COMPOUND_NAME_RE = re.compile(
    r"\b(?:den|der|des|dem)\s+([A-Za-zÄÖÜäöüß]{2,}?)-?timer\b", re.IGNORECASE
)

# Very small genitive/plural cleanup for "für Kartoffeln" -> "Kartoffel".
_PLURAL_SUFFIXES = ("nudeln", "kartoffeln", "eiern", "eier")


def _normalise_name_word(word: str) -> str:
    """Best-effort singular/title form of a single spoken noun.

    Rule-based only (documented limitation, spec open question): strip a
    trailing 'n'/'s' when the word is long enough, then title-case. No word
    list. 'Kartoffeln' -> 'Kartoffel', 'Nudeln' -> 'Nudel', 'Tee' -> 'Tee'.
    """
    w = word.strip()
    if not w:
        return w
    low = w.lower()
    if low.endswith("n") and len(w) > 4 and not low.endswith("en"):
        w = w[:-1]
    elif low.endswith("en") and len(w) > 5:
        w = w[:-1]  # "Kartoffeln"->"Kartoffel" handled by the -n branch; "Nudeln"->"Nudel"
    elif low.endswith("s") and len(w) > 4:
        w = w[:-1]
    return w[:1].upper() + w[1:]


def parse_name(part: str) -> str | None:
    """Explicit name from a set command.

    'für Kartoffeln' -> 'Kartoffel' (explicit form) or the German compound
    noun 'Eiertimer'/'Kartoffeltimer' -> 'Eier'/'Kartoffel' (the more natural
    spoken form — live QA finding 2026-09-17).
    """
    m = _NAME_RE.search(part)
    if m:
        return _normalise_name_word(m.group(1))
    m = _COMPOUND_NAME_RE.search(part)
    if m:
        return _normalise_name_word(m.group(1))
    return None


def parse_ref_name(part: str) -> str | None:
    """Target timer name from a change/query/delete command.

    'Verlängere den Kartoffel Timer um 5 Minuten' -> 'Kartoffel'
    'Verlängere den Kartoffeltimer um 5 Minuten' -> 'Kartoffel' (compound)
    'Wie lange läuft der Timer noch' -> None (no name)
    """
    m = _REF_NAME_RE.search(part)
    if m:
        raw = m.group(1).strip()
        # A single-word reference like "den Timer" leaves raw empty of a name.
        if raw and raw.lower() not in ("den", "der"):
            return raw.strip()
    m = _REF_COMPOUND_NAME_RE.search(part)
    if m:
        return _normalise_name_word(m.group(1))
    return None


def derived_name(parsed: ParsedTime) -> str:
    """Auto name for an unnamed timer: '{duration} Timer' / '{clock} Timer'."""
    if parsed.is_clock and parsed.clock:
        return f"{parsed.clock} Timer"
    return f"{parsed.spoken_duration} Timer"


def wants_all(part: str) -> bool:
    """True for 'lösche alle Timer' / 'brich alle Timer ab'."""
    return re.search(r"\balle\s+timer\b", part, re.IGNORECASE) is not None


# ---------------------------------------------------------------------------
# Intent classification from the matched template
# ---------------------------------------------------------------------------
_INTENT_BY_SERVICE = {
    "timer.set": "set",
    "timer.extend": "extend",
    "timer.shorten": "shorten",
    "timer.query": "query",
    "timer.pause": "pause",
    "timer.resume": "resume",
    "timer.delete": "delete",
}


# extend vs. shorten are near-antonyms of each other and structurally very
# similar sentences ("Verlängere/Verkürze den X Timer um Y Minuten") — live
# testing found Weaviate nearText can rank the wrong one by a margin as thin
# as 0.006 once a name/number dilutes the one-word signal (PROJ-85 QA
# follow-up, 2026-09-16). The verb itself is unambiguous and trivial to check
# lexically, so it overrides a close/wrong semantic match rather than trusting
# the embedding for this specific pair.
_EXTEND_VERB_RE = re.compile(
    r"\bverl[äa]nger|\blänger\b|\bdazu\b|\bspäter\b", re.IGNORECASE
)
# "ab" alone is too common a German word/preposition to use as a bare
# standalone signal (false positives); require it paired with "zieh" ("zieh
# … ab") as in the seeded pattern.
_SHORTEN_VERB_RE = re.compile(
    r"\bverk[üu]rz|\bkürzer\b|\bfrüher\b|\bzieh\w*\b.*\bab\b", re.IGNORECASE
)


def timer_action(
    service: str | None, intent_template: str | None, part: str | None = None
) -> str | None:
    """Map the Weaviate match to a timer action, or None if it is not a timer.

    `part` (the actual spoken/typed text), when given, arbitrates an
    extend/shorten match against the literal verb — see _EXTEND_VERB_RE.
    """
    action: str | None = None
    if service and service in _INTENT_BY_SERVICE:
        action = _INTENT_BY_SERVICE[service]
    elif intent_template and intent_template.startswith("timer:"):
        action = intent_template.split(":", 1)[1]

    if action in ("extend", "shorten") and part:
        wants_extend = _EXTEND_VERB_RE.search(part) is not None
        wants_shorten = _SHORTEN_VERB_RE.search(part) is not None
        if wants_extend and not wants_shorten:
            return "extend"
        if wants_shorten and not wants_extend:
            return "shorten"
        # both or neither matched literally — trust the semantic match

    return action


# ---------------------------------------------------------------------------
# Role + limit resolution
# ---------------------------------------------------------------------------
@dataclass
class RoleConfig:
    role: str
    allowed: bool
    max_active: int
    max_duration_seconds: int


async def resolve_role(pool, user_id: str | None) -> str:
    """Role of the requesting user, read fresh from alice.users.

    A missing / anonymous user (Speech-Gateway could not identify the speaker)
    resolves to the configured `timer_default_role`.
    """
    if user_id and user_id != "00000000-0000-0000-0000-000000000000":
        try:
            row = await pool.fetchrow(
                "SELECT role FROM alice.users WHERE id = $1::uuid", user_id
            )
        except Exception as exc:
            logger.warning("Role lookup failed for %s: %s", user_id, exc)
            row = None
        if row and row["role"]:
            return row["role"]
    return await default_role(pool)


async def default_role(pool) -> str:
    try:
        row = await pool.fetchrow(
            "SELECT value FROM alice.system_settings WHERE key = 'timer_default_role'"
        )
    except Exception as exc:
        logger.warning("timer_default_role lookup failed: %s", exc)
        return "user"
    if not row:
        return "user"
    val = row["value"]
    if isinstance(val, str):
        return val.strip('"') or "user"
    return "user"


async def load_role_config(pool, role: str) -> RoleConfig:
    """Timer permission + caps for a role, from alice.role_templates."""
    try:
        row = await pool.fetchrow(
            "SELECT assistant_permissions FROM alice.role_templates WHERE role = $1",
            role,
        )
    except Exception as exc:
        logger.warning("role_templates lookup failed for %s: %s", role, exc)
        row = None
    ap: dict = {}
    if row and row["assistant_permissions"]:
        ap = row["assistant_permissions"]
        if isinstance(ap, str):
            import json
            try:
                ap = json.loads(ap)
            except Exception:
                ap = {}
    return RoleConfig(
        role=role,
        allowed=bool(ap.get("can_use_timers", True)),
        max_active=int(ap.get("timer_max_active", _FALLBACK_MAX_ACTIVE) or 0),
        max_duration_seconds=int(
            ap.get("timer_max_duration_seconds", _FALLBACK_MAX_DURATION) or 0
        ),
    )


# ---------------------------------------------------------------------------
# DB helpers — every mutation is row-locked / conditional
# ---------------------------------------------------------------------------
async def count_active(pool, role: str) -> int:
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS c FROM alice.timers "
        "WHERE owner_role = $1 AND status = ANY($2::text[])",
        role, list(ACTIVE_STATUSES),
    )
    return int(row["c"])


async def list_active(pool, role: str) -> list[dict]:
    rows = await pool.fetch(
        "SELECT id, name, expires_at, status, paused_remaining_seconds "
        "FROM alice.timers "
        "WHERE owner_role = $1 AND status = ANY($2::text[]) "
        "ORDER BY expires_at ASC",
        role, list(ACTIVE_STATUSES),
    )
    return [dict(r) for r in rows]


async def find_by_name(pool, role: str, name: str) -> list[dict]:
    """Active timers in the role scope whose name matches case-insensitively
    (exact, or the '<name> Timer' variant)."""
    n = name.strip().lower()
    rows = await pool.fetch(
        "SELECT id, name, expires_at, status, paused_remaining_seconds, origin_channel "
        "FROM alice.timers "
        "WHERE owner_role = $1 AND status = ANY($2::text[]) "
        "AND (LOWER(name) = $3 OR LOWER(name) = $3 || ' timer')",
        role, list(ACTIVE_STATUSES), n,
    )
    return [dict(r) for r in rows]


async def name_collision(pool, role: str, name: str) -> bool:
    row = await pool.fetchrow(
        "SELECT 1 FROM alice.timers "
        "WHERE owner_role = $1 AND status = ANY($2::text[]) AND LOWER(name) = LOWER($3) "
        "LIMIT 1",
        role, list(ACTIVE_STATUSES), name,
    )
    return row is not None


async def resolve_collision_name(pool, role: str, base_name: str) -> tuple[str, bool]:
    """Return the name to use and whether a fallback ordinal had to be applied.

    '20 Minuten Timer' taken -> 'zweiter 20 Minuten Timer', then 'dritter …'.
    """
    if not await name_collision(pool, role, base_name):
        return base_name, False
    # strip a trailing " Timer" so the ordinal reads naturally
    core = re.sub(r"\s+timer$", "", base_name, flags=re.IGNORECASE)
    for ordinal in _ORDINALS:
        candidate = f"{ordinal} {core} Timer"
        if not await name_collision(pool, role, candidate):
            return candidate, True
    # extremely unlikely; fall back to a timestamped name
    return f"{core} Timer {int(datetime.now(LOCAL_TZ).timestamp())}", True


async def insert_timer(
    pool, *, owner_user_id: str | None, owner_role: str, name: str,
    expires_at: datetime, origin_channel: str,
) -> dict:
    row = await pool.fetchrow(
        "INSERT INTO alice.timers "
        "(owner_user_id, owner_role, name, expires_at, status, origin_channel) "
        "VALUES ($1, $2, $3, $4, 'running', $5) "
        "RETURNING id, name, expires_at, status",
        owner_user_id, owner_role, name, expires_at, origin_channel,
    )
    return dict(row)


async def change_expiry(pool, timer_id, delta_seconds: int, *, now: datetime | None = None) -> dict | None:
    """Extend / shorten a running timer atomically.

    Row-locked. Returns the updated row, or None if the timer is no longer
    running (expired / paused / deleted in the meantime — the caller reports
    "schon abgelaufen"). A shorten that would push the expiry to <= now is
    rejected with {'rejected': True, 'remaining': <secs>}.
    """
    now = now or datetime.now(LOCAL_TZ)
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, name, expires_at FROM alice.timers "
                "WHERE id = $1::uuid AND status = 'running' FOR UPDATE",
                str(timer_id),
            )
            if row is None:
                return None
            new_expiry = row["expires_at"] + timedelta(seconds=delta_seconds)
            if new_expiry <= now + timedelta(seconds=1):
                remaining = int((row["expires_at"] - now).total_seconds())
                return {"rejected": True, "remaining": max(0, remaining), "name": row["name"]}
            upd = await conn.fetchrow(
                "UPDATE alice.timers SET expires_at = $2 "
                "WHERE id = $1::uuid RETURNING id, name, expires_at",
                str(timer_id), new_expiry,
            )
            return dict(upd)


async def change_paused_remaining(pool, timer_id, delta_seconds: int) -> dict | None:
    """Extend / shorten a *paused* timer's frozen remaining time.

    Row-locked. Returns the updated {name, remaining}, None if the timer is not
    paused (caller then treats it as running/expired), or
    {'rejected': True, 'remaining': …} if the shorten would drop it to ≤ 0.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, name, status, paused_remaining_seconds FROM alice.timers "
                "WHERE id = $1::uuid FOR UPDATE",
                str(timer_id),
            )
            if row is None or row["status"] != "paused":
                return None
            new_rem = int(row["paused_remaining_seconds"] or 0) + delta_seconds
            if new_rem < MIN_DURATION_SECONDS:
                return {
                    "rejected": True, "name": row["name"],
                    "remaining": int(row["paused_remaining_seconds"] or 0),
                }
            await conn.execute(
                "UPDATE alice.timers SET paused_remaining_seconds = $2 "
                "WHERE id = $1::uuid",
                str(timer_id), new_rem,
            )
            return {"name": row["name"], "remaining": new_rem}


async def pause_timer(pool, timer_id, *, now: datetime | None = None) -> dict | None:
    """Freeze a running timer. Returns {'name', 'remaining'} or None (not running)."""
    now = now or datetime.now(LOCAL_TZ)
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, name, expires_at, status FROM alice.timers "
                "WHERE id = $1::uuid FOR UPDATE",
                str(timer_id),
            )
            if row is None:
                return None
            if row["status"] == "paused":
                return {"noop": True, "name": row["name"]}
            if row["status"] != "running":
                return None
            remaining = max(
                0, int((row["expires_at"] - now).total_seconds())
            )
            await conn.execute(
                "UPDATE alice.timers SET status = 'paused', paused_remaining_seconds = $2 "
                "WHERE id = $1::uuid",
                str(timer_id), remaining,
            )
            return {"name": row["name"], "remaining": remaining}


async def resume_timer(pool, timer_id, *, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(LOCAL_TZ)
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, name, status, paused_remaining_seconds FROM alice.timers "
                "WHERE id = $1::uuid FOR UPDATE",
                str(timer_id),
            )
            if row is None:
                return None
            if row["status"] == "running":
                return {"noop": True, "name": row["name"]}
            if row["status"] != "paused":
                return None
            rem = row["paused_remaining_seconds"] or 0
            new_expiry = now + timedelta(seconds=rem)
            await conn.execute(
                "UPDATE alice.timers SET status = 'running', "
                "paused_remaining_seconds = NULL, expires_at = $2 "
                "WHERE id = $1::uuid",
                str(timer_id), new_expiry,
            )
            return {"name": row["name"], "remaining": rem, "expires_at": new_expiry}


async def delete_timer(pool, timer_id) -> dict | None:
    """Delete one timer regardless of status (delete beats a not-yet-acked
    expiry). Returns {'name', 'origin_channel', 'was_expired'} or None."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, name, status, origin_channel FROM alice.timers "
                "WHERE id = $1::uuid FOR UPDATE",
                str(timer_id),
            )
            if row is None:
                return None
            await conn.execute("DELETE FROM alice.timers WHERE id = $1::uuid", str(timer_id))
            return {
                "name": row["name"],
                "origin_channel": row["origin_channel"],
                "was_expired": row["status"] == "expired",
            }


async def delete_all(pool, role: str) -> int:
    row = await pool.fetchrow(
        "WITH d AS (DELETE FROM alice.timers "
        "WHERE owner_role = $1 AND status = ANY($2::text[]) RETURNING 1) "
        "SELECT COUNT(*) AS c FROM d",
        role, list(ACTIVE_STATUSES),
    )
    return int(row["c"])


# ---------------------------------------------------------------------------
# The handler — one spoken part -> one German reply
# ---------------------------------------------------------------------------
@dataclass
class TimerReply:
    text: str
    # Set when a timer was created/changed so the scheduler can be woken and
    # the WebApp response can carry the absolute expiry.
    wake_scheduler: bool = False
    created: dict | None = None       # {id, name, expires_at} for a new timer
    cancelled_channels: list[str] = field(default_factory=list)  # stop a melody


async def handle_timer_part(
    pool, part: str, action: str, *, user_id: str | None, source: str | None,
    now: datetime | None = None,
) -> TimerReply:
    """Resolve one timer command part end to end. Never raises for a normal
    "user said something odd" case — it returns a friendly German reply."""
    now = now or datetime.now(LOCAL_TZ)
    role = await resolve_role(pool, user_id)
    cfg = await load_role_config(pool, role)

    # A role that lost the timer permission can still look at and clear its
    # own running timers (Tech Design G) — only creating / changing is blocked.
    if not cfg.allowed and action not in ("query", "delete"):
        return TimerReply(
            "Timer sind für deine Rolle nicht freigeschaltet. "
            "Ein Administrator kann das in den Einstellungen ändern."
        )

    origin_channel = _origin_channel(source)
    owner_user_id = user_id if (user_id and user_id != "00000000-0000-0000-0000-000000000000") else None

    if action == "set":
        return await _do_set(pool, part, role, cfg, owner_user_id, origin_channel, now)
    if action in ("extend", "shorten"):
        return await _do_change(pool, part, role, cfg, action, now)
    if action == "query":
        return await _do_query(pool, part, role, now)
    if action in ("pause", "resume"):
        return await _do_pause_resume(pool, part, role, action, now)
    if action == "delete":
        return await _do_delete(pool, part, role, now)

    return TimerReply("Das habe ich mit dem Timer nicht verstanden.")


def _origin_channel(source: str | None) -> str:
    """'esphome:Büro' -> 'esphome:Büro' (device key); webapp_* / None -> 'webapp'."""
    if source and source.startswith("esphome:"):
        return source
    if source == "esphome":
        return "esphome"
    return "webapp"


async def _do_set(pool, part, role, cfg: RoleConfig, owner_user_id, origin_channel, now) -> TimerReply:
    parsed = parse_time(part, now=now)
    if parsed.rejected:
        return TimerReply(
            "So lange kann ich keinen Timer stellen — nenn mir eine Dauer in "
            "Minuten oder Stunden oder eine Uhrzeit."
        )
    if parsed.seconds is None:
        return TimerReply("Auf wie viele Minuten soll ich den Timer stellen?")

    if parsed.seconds < MIN_DURATION_SECONDS:
        return TimerReply(
            f"Ein Timer muss mindestens {MIN_DURATION_SECONDS} Sekunden lang sein."
        )
    if cfg.max_duration_seconds and parsed.seconds > cfg.max_duration_seconds:
        return TimerReply(
            f"Für deine Rolle sind Timer bis höchstens "
            f"{_fmt_duration(cfg.max_duration_seconds)} möglich."
        )
    if cfg.max_active and await count_active(pool, role) >= cfg.max_active:
        return TimerReply(
            f"Für deine Rolle sind höchstens {cfg.max_active} Timer gleichzeitig möglich."
        )

    explicit = parse_name(part)
    base_name = f"{explicit} Timer" if explicit else derived_name(parsed)
    name, was_fallback = await resolve_collision_name(pool, role, base_name)

    expires_at = now + timedelta(seconds=parsed.seconds)
    row = await insert_timer(
        pool, owner_user_id=owner_user_id, owner_role=role, name=name,
        expires_at=expires_at, origin_channel=origin_channel,
    )

    # Confirmation wording (spec). On a name collision Alice says so and names
    # the fallback ("Es gibt schon einen 20 Minuten Timer. Ich habe einen
    # zweiten 20 Minuten Timer gesetzt.").
    when = parsed.clock if parsed.is_clock else parsed.spoken_duration
    tail = f", er läuft {parsed.spoken_duration}" if parsed.is_clock else ""

    if was_fallback:
        core = (
            f"Es gibt schon einen {base_name}. "
            f"Ich habe einen {name} auf {when} gesetzt{tail}."
        )
    elif explicit or name != derived_name(parsed):
        core = f"Ich habe den {name} auf {when} gesetzt{tail}."
    else:
        core = f"Ich habe einen Timer auf {when} gesetzt{tail}."

    return TimerReply(
        core, wake_scheduler=True,
        created={"id": str(row["id"]), "name": name, "expires_at": expires_at.isoformat()},
    )


async def _pick_target(pool, part, role, now) -> tuple[dict | None, str | None]:
    """Resolve the target timer for a change/query/pause/delete command.

    Returns (timer_row, error_text). error_text set when the name is unknown or
    ambiguous (nothing is changed by the caller in that case).
    """
    ref = parse_ref_name(part)
    active = await list_active(pool, role)
    if ref:
        matches = await find_by_name(pool, role, ref)
        if not matches:
            if active:
                names = ", ".join(t["name"] for t in active)
                return None, (
                    f"Es gibt keinen {ref} Timer. Aktiv sind gerade: {names}."
                )
            return None, f"Es gibt keinen {ref} Timer, und im Moment läuft auch kein Timer."
        if len(matches) > 1:
            names = ", ".join(t["name"] for t in matches)
            return None, f"Es gibt mehrere passende Timer: {names}. Welchen meinst du?"
        return matches[0], None
    # no name given
    if not active:
        return None, "Es läuft gerade kein Timer."
    if len(active) == 1:
        return active[0], None
    names = ", ".join(
        f"{t['name']} ({_fmt_remaining(_secs_left(t, now))})" for t in active
    )
    return None, f"Es laufen mehrere Timer: {names}. Welchen meinst du?"


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def secs_left(timer: dict, now: datetime | None = None) -> int:
    """Seconds remaining on a timer row (0 for a past expiry, frozen value
    while paused)."""
    now = now or datetime.now(LOCAL_TZ)
    if timer["status"] == "paused":
        return int(timer.get("paused_remaining_seconds") or 0)
    exp = timer["expires_at"]
    return max(0, int((exp - now).total_seconds()))


# backwards-compatible alias used internally
_secs_left = secs_left


async def _do_change(pool, part, role, cfg: RoleConfig, action, now) -> TimerReply:
    target, err = await _pick_target(pool, part, role, now)
    if err:
        return TimerReply(err)
    assert target is not None

    delta = parse_delta(part)
    if delta is None:
        return TimerReply("Um wie viele Minuten soll ich den Timer ändern?")

    signed = -delta if action == "shorten" else delta

    if action == "extend" and cfg.max_duration_seconds:
        projected = _secs_left(target, now) + delta
        if projected > cfg.max_duration_seconds:
            return TimerReply(
                f"Für deine Rolle sind Timer bis höchstens "
                f"{_fmt_duration(cfg.max_duration_seconds)} möglich. "
                f"Der {target['name']} bleibt unverändert."
            )

    # A paused timer changes its frozen remaining time, not an expiry (BUG-3).
    if target["status"] == "paused":
        pres = await change_paused_remaining(pool, target["id"], signed)
        if pres is None:
            return TimerReply(f"Der {target['name']} ist nicht mehr aktiv.")
        if pres.get("rejected"):
            return TimerReply(
                f"So viel kann ich nicht abziehen — der {pres['name']} steht bei "
                f"{_fmt_remaining(pres['remaining'])}."
            )
        return TimerReply(
            f"Der {pres['name']} steht jetzt bei {_fmt_remaining(pres['remaining'])} "
            f"(pausiert).",
            wake_scheduler=True,
        )

    result = await change_expiry(pool, target["id"], signed, now=now)
    if result is None:
        return TimerReply(
            f"Der {target['name']} ist schon abgelaufen. Setz bei Bedarf einen neuen Timer."
        )
    if result.get("rejected"):
        return TimerReply(
            f"So viel kann ich nicht abziehen — der {result['name']} läuft nur noch "
            f"{_fmt_remaining(result['remaining'])}."
        )
    remaining = max(0, int((result["expires_at"] - now).total_seconds()))
    return TimerReply(
        f"Der {result['name']} läuft jetzt noch {_fmt_remaining(remaining)}.",
        wake_scheduler=True,
    )


async def _do_query(pool, part, role, now) -> TimerReply:
    ref = parse_ref_name(part)
    active = await list_active(pool, role)

    # list form
    if not ref and re.search(r"\bwelche|meine\b", part, re.IGNORECASE):
        if not active:
            return TimerReply("Es läuft gerade kein Timer.")
        parts = []
        for t in active:
            label = f"der {t['name']}: noch {_fmt_remaining(_secs_left(t, now))}"
            if t["status"] == "paused":
                label += " (pausiert)"
            parts.append(label)
        return TimerReply("Aktive Timer: " + "; ".join(parts) + ".")

    target, err = await _pick_target(pool, part, role, now)
    if err:
        return TimerReply(err)
    assert target is not None
    left = _secs_left(target, now)
    suffix = " (pausiert)" if target["status"] == "paused" else ""
    return TimerReply(f"Der {target['name']} läuft noch {_fmt_remaining(left)}{suffix}.")


async def _do_pause_resume(pool, part, role, action, now) -> TimerReply:
    target, err = await _pick_target(pool, part, role, now)
    if err:
        return TimerReply(err)
    assert target is not None

    if action == "pause":
        res = await pause_timer(pool, target["id"], now=now)
        if res is None:
            return TimerReply(f"Der {target['name']} ist nicht mehr aktiv.")
        if res.get("noop"):
            return TimerReply(f"Der {res['name']} ist schon pausiert.")
        return TimerReply(
            f"Der {res['name']} ist pausiert, {_fmt_remaining(res['remaining'])} bleiben stehen.",
            wake_scheduler=True,
        )
    else:
        res = await resume_timer(pool, target["id"], now=now)
        if res is None:
            return TimerReply(f"Der {target['name']} ist nicht mehr aktiv.")
        if res.get("noop"):
            return TimerReply(f"Der {res['name']} läuft bereits.")
        return TimerReply(
            f"Der {res['name']} läuft weiter, noch {_fmt_remaining(res['remaining'])}.",
            wake_scheduler=True,
        )


async def _do_delete(pool, part, role, now) -> TimerReply:
    if wants_all(part):
        count = await delete_all(pool, role)
        if count == 0:
            return TimerReply("Es läuft gerade kein Timer.")
        # collect origin channels to stop any melody already playing
        word = "Timer" if count == 1 else "Timer"
        return TimerReply(
            f"Ich habe {count} {word} gelöscht.", wake_scheduler=True,
        )

    target, err = await _pick_target(pool, part, role, now)
    if err:
        return TimerReply(err)
    assert target is not None
    res = await delete_timer(pool, target["id"])
    if res is None:
        return TimerReply(f"Der {target['name']} ist nicht mehr aktiv.")
    channels = [res["origin_channel"]] if res.get("was_expired") else []
    return TimerReply(
        f"Der {res['name']} ist gelöscht.",
        wake_scheduler=True, cancelled_channels=channels,
    )
