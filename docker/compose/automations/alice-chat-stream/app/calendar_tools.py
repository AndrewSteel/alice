"""
PROJ-87 — Kalender-Agent: LLM tools backed by the alice-calendar service.

alice-chat-stream only orchestrates; all calendar logic lives in alice-calendar
(POST {CALENDAR_URL}/internal/tools/<tool>, user's JWT forwarded). Per LLM turn:

  1. start_turn() asks alice-calendar whether the user may use the calendar
     (fresh permission + unknown-speaker check) and fetches the open follow-up
     question of the previous turn. Tool results are not part of the chat
     history, so without this the next turn would lose ticket / event refs.
  2. The tool schema is offered only when enabled; otherwise a system-prompt
     note tells the model to decline and explain why.
  3. execute() forwards tool calls with session_id + turn number, which the
     service needs for the turn-bound delete confirmation.

CALENDAR_URL empty → feature off entirely (no tools, no prompt note).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("alice-chat-stream.calendar")

CALENDAR_URL = os.environ.get("CALENDAR_URL", "").strip().rstrip("/")
CALENDAR_TIMEOUT_SECONDS = float(os.environ.get("CALENDAR_TIMEOUT_SECONDS", "25"))
TURN_TIMEOUT_SECONDS = 3.0

# LLM tool name → alice-calendar tool route
TOOL_ROUTES = {
    "calendar_list_events": "list_events",
    "calendar_create_event": "create_event",
    "calendar_update_event": "update_event",
    "calendar_delete_event": "delete_event",
    "calendar_confirm_delete": "confirm_delete",
}


@dataclass
class CalendarTurn:
    enabled: bool = False
    prompt_lines: list[str] = field(default_factory=list)
    token: str = ""
    session_id: str = ""
    turn: int = 0
    channel: str = "chat"
    # First LLM round may only call one of these calendar tools (see force_decision).
    force_tool: list[str] | None = None
    # Set once a calendar tool asked the user something in this request: the
    # remaining rounds get no tools, so the model must reply instead of e.g.
    # confirming a delete in the same request (live finding 2026-10-05).
    halt_tools: bool = False
    # User's configured language (profile `sprache`) for the templated replies.
    lang: str = "de"


def is_calendar_tool(name: str) -> bool:
    return name in TOOL_ROUTES


def channel_for(source: str | None) -> str:
    return "voice" if source == "esphome" or (source or "").startswith("esphome:") else "chat"


# ---------------------------------------------------------------------------
# Routing + tool forcing (live finding 2026-10-05)
# ---------------------------------------------------------------------------
# 1. The HA fast path matched "Welche Termine habe ich morgen?" to a timer
#    intent and a bare "Nein" to a switch intent — calendar requests and
#    answers to an open calendar question must bypass HA_FAST.
# 2. The deployed model frequently answers without calling a tool and invented
#    "Termin angelegt". For calendar requests the first LLM round therefore
#    offers only the calendar tools with tool_choice="required", so every
#    answer is grounded in a real alice-calendar result.
_CALENDAR_INTENT_RE = re.compile(
    r"(termin|kalender|calendar|appointment|verabredung"
    r"|\bwas\s+steht\b.*\ban\b|\bwas\s+habe?\s+ich\b.*\bvor\b)",
    re.IGNORECASE,
)
_NEGATIVE_RE = re.compile(
    r"^\s*(nein|nee|ne|nö|no|abbrechen|abbruch|stopp?|doch nicht|lieber nicht|vergiss|lass)\b",
    re.IGNORECASE,
)
_AFFIRMATIVE_RE = re.compile(
    r"^\s*(ja|jo|jep|jawohl|genau|richtig|klar|ok(ay)?|bitte|gerne?|mach|lösch|yes|sure)\b",
    re.IGNORECASE,
)

# Which calendar tool a request is about. Order matters: "Lösche den
# Kalendereintrag" is a delete, not a create.
_ACTION_PATTERNS = [
    ("calendar_delete_event", re.compile(
        r"(lösch|losch|entfern|streich|absag|sag\w*\b.*\bab\b|cancel|delete|remove)", re.IGNORECASE)),
    ("calendar_update_event", re.compile(
        r"(verschieb|verleg|änder|aender|umbenenn|benenn\w*\b.*\bum\b|reschedul|rename|\bmove\b|\bchange\b)",
        re.IGNORECASE)),
    ("calendar_create_event", re.compile(
        r"(anleg|leg\w*\b.*\ban\b|erstell|eintrag\b|trag\w*\b.*\bein\b|neue[nrs]?\s+termin|\bsetz"
        r"|notier|vormerk|\bmerk|\bbuch(e|en|st)?\b|\btitel\b|\bdauer\b|\bcreate\b|\badd\b|\bschedule\b"
        r"|\bset\b|\bbook\b|\bplan)", re.IGNORECASE)),
]
# Questions about the calendar → listing only.
_QUESTION_RE = re.compile(
    r"(^\s*(wann|was|welche\w*|wie\s*viele|hab\w*\s+ich|hätte\s+ich|gibt\s+es|steht|zeig\w*|sag\s+mir|lies"
    r"|nenn\w*|when|what|which|how\s+many|do\s+i|show|list)\b|\?\s*$)",
    re.IGNORECASE,
)

# Open calendar questions per chat session: (status, tool, monotonic time).
# Only the immediately following request of the session consumes it.
# In-process is enough: it only steers routing; the authoritative state
# (ticket, refs) lives in alice-calendar/Redis.
_OPEN_QUESTION_TTL = 300.0
_PENDING_STATUSES = {"confirm_delete", "ambiguous", "needs_scope", "needs_calendar", "confirm_past"}
_open_questions: dict[str, tuple[str, str, float]] = {}


def is_calendar_intent(message: str) -> bool:
    return bool(_CALENDAR_INTENT_RE.search(message or ""))


def detect_action(message: str) -> list[str]:
    """Calendar tool(s) a calendar request may need.

    An explicit verb decides; a question means listing; anything else
    (unforeseen verb, e.g. "Setze einen Termin …" before "setz" was known)
    lets the model choose between creating and listing instead of guessing.
    """
    for tool, pattern in _ACTION_PATTERNS:
        if pattern.search(message or ""):
            return [tool]
    if _QUESTION_RE.search(message or ""):
        return ["calendar_list_events"]
    return ["calendar_create_event", "calendar_list_events"]


def take_open_question(session_id: str) -> tuple[str, str] | None:
    """Pop (status, tool) of the open calendar question asked in the previous turn."""
    entry = _open_questions.pop(session_id, None)
    if entry is None or time.monotonic() - entry[2] > _OPEN_QUESTION_TTL:
        return None
    return entry[0], entry[1]


def _track_result(session_id: str, tool: str, result: dict) -> None:
    status = result.get("status")
    if status in _PENDING_STATUSES:
        _open_questions[session_id] = (status, tool, time.monotonic())
    elif status in ("created", "updated", "deleted"):
        _open_questions.pop(session_id, None)


def bypass_fast_path(message: str, open_question: tuple[str, str] | None) -> bool:
    """Calendar request or reply to an open calendar question → LLM path."""
    if not CALENDAR_URL:
        return False
    return open_question is not None or is_calendar_intent(message)


def force_decision(message: str, open_question: tuple[str, str] | None) -> list[str] | None:
    """The calendar tool(s) the first LLM round must choose from, or None."""
    if open_question is not None:
        status, tool = open_question
        if _NEGATIVE_RE.match(message or ""):
            return None
        if status == "confirm_delete":
            # Deleting needs an explicit yes; anything else is answered freely.
            return ["calendar_confirm_delete"] if _AFFIRMATIVE_RE.match(message or "") else None
        return [tool]
    if is_calendar_intent(message):
        return detect_action(message)
    return None


def round_tools(base_tools: list[dict], ct: "CalendarTurn | None", round_no: int) -> tuple[list[dict], str | None]:
    """Tool list + tool_choice for one LLM round."""
    if ct is None or not ct.enabled:
        return base_tools, None
    if ct.halt_tools:
        return [], None
    if ct.force_tool and round_no == 1:
        return [t for t in schema() if t["function"]["name"] in ct.force_tool], "required"
    return base_tools + schema(), None


# ---------------------------------------------------------------------------
# Turn start
# ---------------------------------------------------------------------------
_PROMPT_ENABLED = [
    "",
    "### Kalender (Google)",
    "Für Termine des Nutzers die calendar_*-Tools verwenden (anzeigen, anlegen, ändern, löschen). "
    "Datumsangaben selbst anhand des aktuellen Datums in YYYY-MM-DD umrechnen, Uhrzeiten als HH:MM.",
    "Melde einen Termin NUR dann als angelegt, geändert oder gelöscht, wenn das Tool-Ergebnis "
    "status created/updated/deleted enthält — sonst nicht, und erfinde nie Termine.",
    "Enthält ein Ergebnis eine Rückfrage (status needs_calendar, ambiguous, needs_scope, "
    "confirm_past, confirm_delete), stelle dem Nutzer genau diese Frage und warte auf seine Antwort.",
    "Löschen ist zweistufig: calendar_delete_event liefert ein ticket; calendar_confirm_delete erst "
    "im nächsten Turn nach ausdrücklichem Ja des Nutzers aufrufen. Bei Nein oder Themenwechsel "
    "nichts löschen.",
    "Wochentage und Uhrzeiten aus den Ergebnissen übernehmen und in der Antwortsprache "
    "formulieren; keine eigenen Wochentagsberechnungen für vorhandene Termine.",
    "Antworte bei Kalenderthemen KURZ: ein bis zwei Sätze. Keine Wiederholung der Anfrage, keine "
    "Aufzählung aller Felder, keine Erklärungen zu internen Abläufen und keine technischen Begriffe "
    "(Ticket, Tool, single, series, Status). Keine Rückfragen zu Angaben, die der Nutzer nicht "
    "genannt hat (Erinnerung, Ort, Kalender) — die Standardwerte gelten.",
    "Bei einer Serie fragst du nur, wenn das Ergebnis es verlangt: „Nur diesen Termin oder die "
    "ganze Serie?“.",
]

_PROMPT_VOICE = [
    "Die Antwort wird vorgelesen: keine Listen, kein Markdown, keine Emojis; Termine als "
    "fließender Satz, Uhrzeiten gesprochen (z. B. „um zehn Uhr“).",
]

_PROMPT_FORBIDDEN = [
    "",
    "### Kalender",
    "Die Rolle dieses Nutzers hat keinen Kalenderzugriff. Bei Fragen zu Terminen oder Kalendern "
    "höflich ablehnen und erklären, dass seine Rolle keinen Kalenderzugriff hat.",
]

_PROMPT_UNKNOWN_SPEAKER = [
    "",
    "### Kalender",
    "Der Sprecher wurde nicht erkannt. Bei Fragen zu Terminen oder Kalendern keine Aktion "
    "ausführen und erklären, dass du nicht weißt, wessen Kalender gemeint ist.",
]

_PROMPT_UNAVAILABLE = [
    "",
    "### Kalender",
    "Der Kalender-Dienst ist gerade nicht erreichbar. Bei Fragen zu Terminen sagen, dass der "
    "Kalender momentan nicht erreichbar ist; keine Termine erfinden.",
]


def _pending_lines(pending: dict | None) -> list[str]:
    if not pending:
        return []
    return [
        "",
        "Offene Kalender-Rückfrage aus deiner letzten Antwort (Tool, Argumente, Ergebnis). "
        "Bezieht sich die neue Nachricht darauf, setze den Vorgang mit diesen Daten fort "
        "(event_ref / ticket übernehmen); sonst ignorieren:",
        json.dumps(pending, ensure_ascii=False)[:4000],
    ]


async def start_turn(
    client: httpx.AsyncClient,
    token: str,
    session_id: str,
    turn: int,
    source: str | None,
) -> CalendarTurn:
    """Never raises — a failing calendar must not break the chat."""
    ct = CalendarTurn(token=token, session_id=session_id, turn=turn, channel=channel_for(source))
    if not CALENDAR_URL:
        return ct
    try:
        resp = await client.post(
            f"{CALENDAR_URL}/internal/turn",
            json={"session_id": session_id, "turn": turn},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TURN_TIMEOUT_SECONDS,
        )
        data = resp.json() if resp.status_code == 200 else None
    except Exception as exc:
        logger.warning("calendar turn start failed: %s", exc)
        data = None

    if data is None:
        ct.prompt_lines = list(_PROMPT_UNAVAILABLE)
        return ct
    if data.get("enabled"):
        ct.enabled = True
        ct.prompt_lines = (_PROMPT_ENABLED + (_PROMPT_VOICE if ct.channel == "voice" else [])
                           + _pending_lines(data.get("pending")))
    elif data.get("reason") == "unknown_speaker":
        ct.prompt_lines = list(_PROMPT_UNKNOWN_SPEAKER)
    else:
        ct.prompt_lines = list(_PROMPT_FORBIDDEN)
    return ct


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------
async def execute(name: str, args: dict[str, Any], client: httpx.AsyncClient, ct: CalendarTurn) -> dict:
    """Run one calendar tool call. Always returns a dict — never raises."""
    route = TOOL_ROUTES.get(name)
    if route is None or not CALENDAR_URL or not ct.enabled:
        return {"error": "calendar_disabled", "message": "Kalender ist für diesen Nutzer nicht verfügbar."}
    if ct.halt_tools:
        # A question to the user is open in this request (e.g. a parallel
        # delete + confirm in one round) — nothing may run before the answer.
        return {"error": "await_user_answer",
                "message": "Es wurde NICHTS ausgeführt. Stelle dem Nutzer die offene Frage und warte "
                           "auf seine Antwort."}
    try:
        resp = await client.post(
            f"{CALENDAR_URL}/internal/tools/{route}",
            json={"args": args or {}, "session_id": ct.session_id, "turn": ct.turn, "channel": ct.channel},
            headers={"Authorization": f"Bearer {ct.token}"},
            timeout=CALENDAR_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        logger.warning("calendar tool %s timed out", name)
        return {"error": "timeout", "tool": name,
                "message": "Der Kalender hat nicht rechtzeitig geantwortet. Melde keinen Erfolg."}
    except Exception as exc:
        logger.warning("calendar tool %s failed: %s", name, exc)
        return {"error": "calendar_unavailable", "message": "Der Kalender ist gerade nicht erreichbar."}
    if resp.status_code != 200:
        return {"error": "calendar_unavailable",
                "message": f"Der Kalender-Dienst antwortete mit HTTP {resp.status_code}. Melde keinen Erfolg."}
    try:
        data = resp.json()
    except Exception:
        return {"error": "calendar_unavailable", "message": "Ungültige Antwort vom Kalender-Dienst."}
    if not isinstance(data, dict):
        return {"error": "calendar_unavailable"}
    if ct.session_id:
        _track_result(ct.session_id, name, data)
    if data.get("status") in _PENDING_STATUSES:
        ct.halt_tools = True
    return data


# ---------------------------------------------------------------------------
# UI status texts (same style as streaming._build_tool_status/_summary)
# ---------------------------------------------------------------------------
def tool_status(name: str, args: dict[str, Any]) -> str:
    title = str(args.get("title") or args.get("title_query") or "").strip()
    if name == "calendar_list_events":
        return "Lese Kalender…"
    if name == "calendar_create_event":
        return f"Lege Termin '{title}' an…" if title else "Lege Termin an…"
    if name == "calendar_update_event":
        return f"Ändere Termin '{title}'…" if title else "Ändere Termin…"
    if name == "calendar_delete_event":
        return f"Suche Termin '{title}'…" if title else "Suche Termin…"
    if name == "calendar_confirm_delete":
        return "Lösche Termin…"
    return "Kalender…"


def tool_summary(name: str, result: dict[str, Any]) -> str:
    status = result.get("status")
    if status == "ok":
        n = int(result.get("total") or 0)
        return "Keine Termine" if n == 0 else f"{n} Termin{'e' if n != 1 else ''}"
    return {
        "created": "Termin angelegt",
        "updated": "Termin geändert",
        "deleted": "Termin gelöscht",
        "confirm_delete": "Rückfrage vor dem Löschen",
        "ambiguous": "Mehrere Termine passen",
        "needs_scope": "Serientermin — Rückfrage",
        "needs_calendar": "Kalender wählen",
        "confirm_past": "Termin liegt in der Vergangenheit",
        "not_found": "Kein Termin gefunden",
    }.get(status or "", "")


# ---------------------------------------------------------------------------
# Tool schema (OpenAI function-calling format)
# ---------------------------------------------------------------------------
_RANGE_DESC_KEYS = ("today", "tomorrow", "day_after_tomorrow", "this_week", "next_week", "date", "next")
_RANGE_DESC = (
    "today | tomorrow | day_after_tomorrow | this_week (heute bis Sonntag) | next_week (Mo–So) | "
    "date (konkreter Tag, ggf. bis date_to) | next (nächster anstehender Termin)"
)
_SEARCH_PROPS = {
    "title_query": {"type": "string", "description": "Vom Nutzer genannter Titel/Stichwort des Termins, unverändert"},
    "date": {"type": "string", "description": "Tag des Termins YYYY-MM-DD, falls genannt"},
    "time": {"type": "string", "description": "Startzeit HH:MM, falls genannt (zur Unterscheidung)"},
    "event_ref": {"type": "string", "description": "event_ref aus einer vorherigen Rückfrage (ambiguous/needs_scope)"},
    "scope": {"type": "string", "enum": ["single", "series"],
              "description": "NUR setzen, wenn ein vorheriges Ergebnis status needs_scope hatte und der "
                             "Nutzer geantwortet hat: single = nur dieser Termin, series = ganze Serie"},
}


def schema() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "calendar_list_events",
                "description": "Zeigt Termine aus allen aktivierten Google-Kalendern des Nutzers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "range": {"type": "string", "enum": list(_RANGE_DESC_KEYS), "description": _RANGE_DESC},
                        "date": {"type": "string", "description": "Bei range=date: YYYY-MM-DD"},
                        "date_to": {"type": "string", "description": "Optional bei range=date: letzter Tag YYYY-MM-DD"},
                    },
                    "required": ["range"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "calendar_create_event",
                "description": (
                    "Legt einen Termin an. Ohne start_time ganztägig; Standarddauer 60 Minuten; ohne "
                    "calendar im Standard-Kalender. Komplexe Wiederholungen (z.B. jeden zweiten Dienstag "
                    "im Monat) NICHT anlegen, sondern auf Google verweisen."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "date": {"type": "string", "description": "YYYY-MM-DD"},
                        "start_time": {"type": "string", "description": "HH:MM, leer = ganztägig"},
                        "end_time": {"type": "string", "description": "HH:MM (alternativ zu duration_minutes)"},
                        "duration_minutes": {"type": "integer"},
                        "end_date": {"type": "string", "description": "Letzter Tag bei mehrtägigen ganztägigen Terminen"},
                        "location": {"type": "string"},
                        "description": {"type": "string"},
                        "calendar": {"type": "string", "description": "Vom Nutzer genannter Kalendername"},
                        "reminder_minutes": {"type": "integer", "description": "Erinnerung X Minuten vorher"},
                        "recurrence": {
                            "type": "object",
                            "description": "Nur einfache Wiederholung",
                            "properties": {
                                "freq": {"type": "string", "enum": ["daily", "weekly", "monthly", "yearly"]},
                                "weekdays": {"type": "array", "items": {"type": "string"},
                                             "description": "Nur weekly: MO TU WE TH FR SA SU"},
                                "until": {"type": "string", "description": "Letzter Tag YYYY-MM-DD"},
                                "count": {"type": "integer", "description": "Anzahl Termine"},
                            },
                            "required": ["freq"],
                        },
                        "confirm_past": {"type": "boolean",
                                         "description": "Nur true nach Bestätigung des Nutzers (confirm_past)"},
                    },
                    "required": ["title", "date"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "calendar_update_event",
                "description": (
                    "Ändert einen bestehenden Termin (Titel, Datum/Uhrzeit, Dauer, Ort, Beschreibung, "
                    "Erinnerung, Kalender). Termin über title_query/date/time oder event_ref finden; nur "
                    "die zu ändernden new_*-Felder setzen."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        **_SEARCH_PROPS,
                        "new_title": {"type": "string"},
                        "new_date": {"type": "string", "description": "YYYY-MM-DD"},
                        "new_start_time": {"type": "string", "description": "HH:MM"},
                        "new_end_time": {"type": "string", "description": "HH:MM"},
                        "new_duration_minutes": {"type": "integer"},
                        "new_all_day": {"type": "boolean"},
                        "new_location": {"type": "string"},
                        "new_description": {"type": "string"},
                        "new_reminder_minutes": {"type": "integer"},
                        "new_calendar": {"type": "string"},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "calendar_delete_event",
                "description": (
                    "Stufe 1 des Löschens: findet den Termin und liefert ein ticket. Löscht NOCH NICHT. "
                    "Danach den Nutzer fragen."
                ),
                "parameters": {"type": "object", "properties": dict(_SEARCH_PROPS), "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "calendar_confirm_delete",
                "description": (
                    "Stufe 2: löscht den Termin. Nur im Turn NACH der Rückfrage aufrufen, wenn der Nutzer "
                    "ausdrücklich zugestimmt hat."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"ticket": {"type": "string", "description": "ticket aus calendar_delete_event"}},
                    "required": ["ticket"],
                },
            },
        },
    ]

