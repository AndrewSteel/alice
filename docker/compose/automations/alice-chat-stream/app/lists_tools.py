"""
PROJ-106 — Aufgaben & Listen: LLM tools backed by the alice-lists service.

Same orchestration as the calendar (PROJ-87, see calendar_tools.py): all list
logic lives in alice-lists (POST {LISTS_URL}/internal/tools/<tool>, user's JWT
forwarded); this module decides routing, offers / forces the tools and runs
them. Per request:

  1. classify() decides deterministically — before HA_FAST and the LLM —
     whether a message is about the calendar, lists, or a general day query
     ("Was steht morgen an?") that needs both (lists_agenda).
  2. start_turn() asks alice-lists whether the user may use lists and fetches
     the open follow-up question of the previous turn.
  3. The first LLM round is forced to a lists tool (tool_choice=required) so
     no answer is invented; replies come from lists_replies templates.

LISTS_URL empty → feature off entirely.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import calendar_tools

logger = logging.getLogger("alice-chat-stream.lists")

LISTS_URL = os.environ.get("LISTS_URL", "").strip().rstrip("/")
LISTS_TIMEOUT_SECONDS = float(os.environ.get("LISTS_TIMEOUT_SECONDS", "10"))
TURN_TIMEOUT_SECONDS = 3.0

# LLM tool name → alice-lists tool route ("agenda" runs here, see agenda()).
TOOL_ROUTES = {
    "lists_add_items": "add_items",
    "lists_query_items": "query_items",
    "lists_complete_items": "complete_items",
    "lists_reopen_items": "reopen_items",
    "lists_update_item": "update_item",
    "lists_remove_items": "remove_items",
    "lists_confirm_delete": "confirm_delete",
    "lists_cleanup": "cleanup_list",
    "lists_manage": "manage_list",
    "lists_agenda": "agenda",
}

QUESTION_STATUSES = {
    "confirm_delete", "confirm_delete_list", "ambiguous", "ambiguous_list", "needs_list_scope",
    "unknown_list", "confirm_past", "confirm_order", "confirm_duplicate",
}
_RESOLVED_STATUSES = {"added", "completed", "reopened", "updated", "removed", "deleted", "cleaned",
                      "list_created", "list_renamed", "default_set", "shopping_set"}


@dataclass
class ListsTurn:
    enabled: bool = False
    reason: str | None = None        # forbidden | unavailable when not enabled
    unknown_speaker: bool = False
    prompt_lines: list[str] = field(default_factory=list)
    token: str = ""
    session_id: str = ""
    turn: int = 0
    channel: str = "chat"
    lang: str = "de"
    force_tool: list[str] | None = None
    halt_tools: bool = False
    # The user's message is an explicit "yes" — the only case in which a
    # delete is confirmed (server-side guard, not left to the model).
    affirmed: bool = False


def is_lists_tool(name: str) -> bool:
    return name in TOOL_ROUTES


# ---------------------------------------------------------------------------
# Routing (deterministic, before HA_FAST and the LLM)
# ---------------------------------------------------------------------------
# Spec: "Termin"/"Kalender"/"was habe ich … vor" → calendar only (PROJ-87);
# "Aufgabe"/"zu erledigen"/"Frist"/"fällig"/"überfällig" or a list → lists only;
# a general day query → both, combined.
_LISTS_INTENT_RE = re.compile(
    r"(aufgabe|\btodos?\b|to-?do|zu\s+erledigen|erledigt\b|\bhak(e|en|t)?\b|abhak|\bfrist|fällig|faellig"
    r"|liste\b|listen\b|einkaufszettel|\bzettel\b|spätestens|spaetestens"
    r"|,\s*(sehr\s+)?(wichtig|dringend|unwichtig)\s*[.!]?\s*$"
    r"|\btasks?\b|deadline|\bdue\b|overdue|shopping|\blists?\b)",
    re.IGNORECASE,
)
# Reopening ("Öffne Reifen wechseln wieder", "Butter ist doch nicht da") has
# no list keyword and overlaps with devices ("Öffne den Rolladen wieder"):
# HA_FAST gets the first try, only a non-match is forced onto the lists tools.
_SOFT_LISTS_RE = re.compile(
    r"(\böffne\w*\b.*\bwieder\b|\bdoch\s+nicht\s+(da|erledigt|gekauft|fertig)\b)", re.IGNORECASE,
)
_AGENDA_RE = re.compile(
    r"(\bwas\s+steht\b.*\ban\b|\bwas\s+liegt\b.*\ban\b"
    r"|\bwas\s+(habe|hab|hätte)\s+ich\s+(heute|morgen|übermorgen|diese\s+woche|nächste\s+woche|am\s+\w+)\s*\??\s*$"
    r"|tagesübersicht|\bmein\s+tag\b|what'?s\s+(on|up|planned)|what\s+do\s+i\s+have\s+(today|tomorrow))",
    re.IGNORECASE,
)
_NEGATIVE_RE = re.compile(
    r"^\s*(nein|nee|ne|nö|no|abbrechen|abbruch|stopp?|doch nicht|lieber nicht|vergiss|lass)\b", re.IGNORECASE,
)
_AFFIRMATIVE_RE = re.compile(
    r"^\s*(ja|jo|jep|jawohl|genau|richtig|klar|ok(ay)?|bitte|gerne?|mach|lösch|yes|sure)\b", re.IGNORECASE,
)
# A question about lists (no change requested) → reading tools only.
_QUESTION_RE = re.compile(
    r"(^\s*(was|welche\w*|wie\s*viele|steht|stehen|hab\w*\s+ich|gibt\s+es|zeig\w*|lies|nenn\w*|sag\s+mir"
    r"|what|which|how\s+many|is\s+there|show|list)\b|\?\s*$)",
    re.IGNORECASE,
)
_CHANGE_VERB_RE = re.compile(
    r"\b(setz|schreib|füg|pack|leg\w*\b.*\ban\b|neue|trag|notier|merk|hak|lösch|entfern|streich"
    r"|nimm|änder|aender|verschieb|umbenenn|benenn|öffne|räum|mach|kannst\s+du|add|remove|delete|rename|tick)",
    re.IGNORECASE,
)

_OPEN_QUESTION_TTL = 300.0
_open_questions: dict[str, tuple[str, str, float]] = {}


def classify(message: str, open_question: tuple[str, str] | None = None) -> str | None:
    """"lists" | "lists_soft" | "agenda" | "calendar" | None for a user message."""
    msg = message or ""
    if open_question is not None:
        return "lists"
    if not LISTS_URL:
        return None
    if calendar_tools.is_explicit_calendar_intent(msg):
        return "calendar"
    if _LISTS_INTENT_RE.search(msg):
        return "lists"
    if _AGENDA_RE.search(msg):
        return "agenda"
    if _SOFT_LISTS_RE.search(msg):
        return "lists_soft"
    return None


def take_open_question(session_id: str) -> tuple[str, str] | None:
    """Pop (status, tool) of the open lists question asked in the previous turn."""
    entry = _open_questions.pop(session_id, None)
    if entry is None or time.monotonic() - entry[2] > _OPEN_QUESTION_TTL:
        return None
    return entry[0], entry[1]


def _track_result(session_id: str, tool: str, result: dict) -> None:
    status = result.get("status")
    if status in QUESTION_STATUSES:
        _open_questions[session_id] = (status, tool, time.monotonic())
    elif status in _RESOLVED_STATUSES:
        _open_questions.pop(session_id, None)


def bypass_fast_path(kind: str | None) -> bool:
    """Lists requests, day queries and replies to an open lists question
    must not be captured by HA_FAST (spec AC)."""
    return bool(LISTS_URL) and kind in ("lists", "agenda")


_READ_TOOLS = ["lists_query_items", "lists_manage"]
_ALL_TOOLS = [t for t in TOOL_ROUTES if t not in ("lists_confirm_delete", "lists_agenda")]


def force_decision(message: str, kind: str | None, open_question: tuple[str, str] | None) -> list[str] | None:
    """The lists tool(s) the first LLM round must choose from, or None."""
    msg = message or ""
    if open_question is not None:
        status, tool = open_question
        if _NEGATIVE_RE.match(msg):
            return None
        if status in ("confirm_delete", "confirm_delete_list"):
            return ["lists_confirm_delete"] if _AFFIRMATIVE_RE.match(msg) else None
        return [tool]
    if kind == "agenda":
        return ["lists_agenda"]
    if kind not in ("lists", "lists_soft"):
        return None
    if _QUESTION_RE.search(msg) and not _CHANGE_VERB_RE.search(msg):
        return list(_READ_TOOLS)
    return list(_ALL_TOOLS)


def round_tools(
    base_tools: list[dict],
    ct: "calendar_tools.CalendarTurn | None",
    lt: "ListsTurn | None",
    round_no: int,
) -> tuple[list[dict], str | None]:
    """Tool list + tool_choice for one LLM round (calendar and lists)."""
    if lt is None or not lt.enabled:
        return calendar_tools.round_tools(base_tools, ct, round_no)
    if lt.halt_tools or (ct is not None and ct.enabled and ct.halt_tools):
        return [], None
    if lt.force_tool and round_no == 1:
        return [t for t in schema() if t["function"]["name"] in lt.force_tool], "required"
    tools, choice = calendar_tools.round_tools(base_tools, ct, round_no)
    if choice == "required":
        return tools, choice
    return tools + [t for t in schema() if t["function"]["name"] != "lists_agenda"], None


# ---------------------------------------------------------------------------
# Turn start
# ---------------------------------------------------------------------------
_PROMPT_ENABLED = [
    "",
    "### Aufgaben & Listen",
    "Für Einkaufsliste, Aufgaben und Listen des Nutzers die lists_*-Tools verwenden. Einträge genau so "
    "übergeben, wie der Nutzer sie gesagt hat (z. B. items='Milch, Butter und Eier') — NICHT selbst "
    "aufteilen oder umformulieren. Ohne Listenname gilt die Standardliste.",
    "„am …/um …“ = Fälligkeit (due_date/due_time), „bis …/spätestens …“ = Frist (deadline_date/deadline_time), "
    "„wichtig/dringend“ = priority high, „unwichtig/irgendwann“ = low. Datumsangaben selbst anhand des aktuellen "
    "Datums in YYYY-MM-DD umrechnen, Uhrzeiten als HH:MM. Nicht genannte Angaben weglassen und NIE erfragen.",
    "Melde nur Ergebnisse aus Tool-Antworten; erfinde keine Einträge und keine Erfolge.",
    "Enthält ein Ergebnis eine Rückfrage, stelle genau diese Frage. Bestätigt der Nutzer im nächsten Turn, das "
    "Tool mit denselben Argumenten und confirmed=true erneut aufrufen; bei Auswahl item_ref bzw. den "
    "Listennamen übernehmen.",
    "Löschen außerhalb der Einkaufsliste ist zweistufig: lists_remove_items liefert ein ticket; "
    "lists_confirm_delete erst im nächsten Turn nach ausdrücklichem Ja.",
]

_PROMPT_UNKNOWN_SPEAKER = [
    "Der Sprecher wurde nicht erkannt: erlaubt ist nur, Einträge auf die Einkaufsliste zu setzen.",
]

_PROMPT_FORBIDDEN = [
    "",
    "### Aufgaben & Listen",
    "Die Rolle dieses Nutzers hat keinen Zugriff auf Aufgaben und Listen. Bei solchen Fragen höflich "
    "ablehnen und das als Grund nennen.",
]

_PROMPT_UNAVAILABLE = [
    "",
    "### Aufgaben & Listen",
    "Der Listen-Dienst ist gerade nicht erreichbar. Bei Fragen zu Aufgaben oder Listen das sagen; "
    "keine Einträge erfinden.",
]


def _pending_lines(pending: dict | None) -> list[str]:
    if not pending:
        return []
    return [
        "",
        "Offene Listen-Rückfrage aus deiner letzten Antwort (Tool, Argumente, Ergebnis). Bezieht sich die "
        "neue Nachricht darauf, setze den Vorgang mit diesen Daten fort (ticket / item_ref / Argumente "
        "übernehmen, bei Zustimmung confirmed=true); sonst ignorieren:",
        json.dumps(pending, ensure_ascii=False, default=str)[:4000],
    ]


async def start_turn(client: httpx.AsyncClient, token: str, session_id: str, turn: int,
                     source: str | None) -> ListsTurn:
    """Never raises — a failing lists service must not break the chat."""
    lt = ListsTurn(token=token, session_id=session_id, turn=turn, channel=calendar_tools.channel_for(source))
    if not LISTS_URL:
        return lt
    try:
        resp = await client.post(
            f"{LISTS_URL}/internal/turn",
            json={"session_id": session_id, "turn": turn},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TURN_TIMEOUT_SECONDS,
        )
        data = resp.json() if resp.status_code == 200 else None
    except Exception as exc:
        logger.warning("lists turn start failed: %s", exc)
        data = None

    if data is None:
        lt.reason = "unavailable"
        lt.prompt_lines = list(_PROMPT_UNAVAILABLE)
        return lt
    if data.get("enabled"):
        lt.enabled = True
        lt.unknown_speaker = bool(data.get("unknown_speaker"))
        lt.prompt_lines = (_PROMPT_ENABLED + (_PROMPT_UNKNOWN_SPEAKER if lt.unknown_speaker else [])
                           + _pending_lines(data.get("pending")))
    else:
        lt.reason = data.get("reason") or "forbidden"
        lt.prompt_lines = list(_PROMPT_FORBIDDEN)
    return lt


def prepare(lt: ListsTurn, message: str, kind: str | None, open_question: tuple[str, str] | None) -> None:
    lt.affirmed = bool(_AFFIRMATIVE_RE.match(message or ""))
    if lt.enabled:
        lt.force_tool = force_decision(message, kind, open_question)


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------
async def _call(client: httpx.AsyncClient, lt: ListsTurn, route: str, args: dict) -> dict:
    try:
        resp = await client.post(
            f"{LISTS_URL}/internal/tools/{route}",
            json={"args": args or {}, "session_id": lt.session_id, "turn": lt.turn, "channel": lt.channel},
            headers={"Authorization": f"Bearer {lt.token}"},
            timeout=LISTS_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        logger.warning("lists tool %s timed out", route)
        return {"error": "timeout", "message": "Der Listen-Dienst hat nicht rechtzeitig geantwortet."}
    except Exception as exc:
        logger.warning("lists tool %s failed: %s", route, exc)
        return {"error": "lists_unavailable", "message": "Der Listen-Dienst ist gerade nicht erreichbar."}
    if resp.status_code != 200:
        return {"error": "lists_unavailable", "message": f"Listen-Dienst HTTP {resp.status_code}."}
    try:
        data = resp.json()
    except Exception:
        return {"error": "lists_unavailable", "message": "Ungültige Antwort vom Listen-Dienst."}
    return data if isinstance(data, dict) else {"error": "lists_unavailable"}


async def execute(name: str, args: dict[str, Any], client: httpx.AsyncClient, lt: ListsTurn,
                  ct: "calendar_tools.CalendarTurn | None" = None) -> dict:
    """Run one lists tool call. Always returns a dict — never raises."""
    route = TOOL_ROUTES.get(name)
    if route is None or not LISTS_URL or not lt.enabled:
        return {"error": "lists_disabled", "message": "Listen sind für diesen Nutzer nicht verfügbar."}
    if lt.halt_tools:
        return {"error": "await_user_answer",
                "message": "Es wurde NICHTS ausgeführt. Stelle dem Nutzer die offene Frage und warte auf seine "
                           "Antwort."}
    if route == "confirm_delete" and not lt.affirmed:
        # "Nein" or anything but an explicit yes never deletes (spec AC).
        return {"error": "not_confirmed", "message": "Der Nutzer hat nicht zugestimmt. Es wurde NICHTS gelöscht."}
    if route == "agenda":
        return await agenda(args, client, lt, ct)
    data = await _call(client, lt, route, args)
    if lt.session_id:
        _track_result(lt.session_id, name, data)
    if data.get("status") in QUESTION_STATUSES:
        lt.halt_tools = True
    return data


_AGENDA_RANGES = ("today", "tomorrow", "day_after_tomorrow", "this_week", "next_week", "date")


async def agenda(args: dict, client: httpx.AsyncClient, lt: ListsTurn,
                 ct: "calendar_tools.CalendarTurn | None") -> dict:
    """General day query: calendar events and due entries/deadlines, fetched
    in parallel and answered together (PROJ-87 change by PROJ-106)."""
    rng = str(args.get("range") or "today").strip().lower()
    if rng not in _AGENDA_RANGES:
        rng = "today"
    query = {"range": rng}
    for key in ("date", "date_to"):
        if args.get(key):
            query[key] = args[key]

    async def _calendar():
        if ct is None or not ct.enabled:
            return None
        return await calendar_tools.execute("calendar_list_events", dict(query), client, ct)

    cal_result, lists_result = await asyncio.gather(_calendar(), _call(client, lt, "query_items", dict(query)))
    return {"status": "agenda", "calendar": cal_result, "lists": lists_result}


# ---------------------------------------------------------------------------
# UI status texts (same style as streaming._build_tool_status/_summary)
# ---------------------------------------------------------------------------
def tool_status(name: str, args: dict[str, Any]) -> str:
    return {
        "lists_add_items": "Trage in Liste ein…",
        "lists_query_items": "Lese Listen…",
        "lists_complete_items": "Hake ab…",
        "lists_reopen_items": "Öffne Eintrag wieder…",
        "lists_update_item": "Ändere Eintrag…",
        "lists_remove_items": "Entferne Eintrag…",
        "lists_confirm_delete": "Lösche…",
        "lists_cleanup": "Räume Liste auf…",
        "lists_manage": "Verwalte Listen…",
        "lists_agenda": "Lese Termine und Aufgaben…",
    }.get(name, "Listen…")


def tool_summary(name: str, result: dict[str, Any]) -> str:
    status = result.get("status")
    if status == "ok":
        n = int(result.get("total") or 0)
        return "Keine Einträge" if n == 0 else f"{n} Eintr{'äge' if n != 1 else 'ag'}"
    return {
        "added": "Eingetragen",
        "completed": "Abgehakt",
        "reopened": "Wieder geöffnet",
        "updated": "Geändert",
        "removed": "Entfernt",
        "deleted": "Gelöscht",
        "cleaned": "Aufgeräumt",
        "list_created": "Liste angelegt",
        "list_renamed": "Liste umbenannt",
        "default_set": "Standardliste gesetzt",
        "shopping_set": "Einkaufsliste gesetzt",
        "lists": "Listen",
        "agenda": "Tagesübersicht",
        "not_found": "Nicht gefunden",
        "list_not_found": "Liste nicht gefunden",
    }.get(status or "", "Rückfrage" if status in QUESTION_STATUSES else "")


# ---------------------------------------------------------------------------
# Tool schema (OpenAI function-calling format)
# ---------------------------------------------------------------------------
_LIST_PROP = {"type": "string", "description": "Vom Nutzer genannter Listenname, unverändert (leer = Standardliste)"}
_SCOPE_PROP = {"type": "string", "enum": ["private", "shared"],
               "description": "NUR nach Rückfrage needs_list_scope: private oder gemeinsame Liste"}
_CONFIRMED_PROP = {"type": "boolean", "description": "NUR true, wenn der Nutzer eine Rückfrage bejaht hat"}
_ITEMS_PROP = {"type": "string", "description": "Eintrag/Einträge genau wie gesagt, z. B. 'Milch, Butter und Eier'"}
_REF_PROP = {"type": "string", "description": "item_ref aus einer vorherigen Rückfrage (ambiguous)"}
_DATE_PROPS = {
    "due_date": {"type": "string", "description": "Fälligkeit YYYY-MM-DD („am …“)"},
    "due_time": {"type": "string", "description": "Fälligkeit Uhrzeit HH:MM („um …“)"},
    "deadline_date": {"type": "string", "description": "Frist YYYY-MM-DD („bis …“, „spätestens …“)"},
    "deadline_time": {"type": "string", "description": "Frist Uhrzeit HH:MM"},
}
_RANGE_PROP = {"type": "string",
               "enum": ["today", "tomorrow", "day_after_tomorrow", "this_week", "next_week", "date", "overdue", "all"],
               "description": "Zeitraum (overdue = überfällig, all = ohne Datumsfilter)"}


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []},
    }}


def schema() -> list[dict]:
    return [
        _fn("lists_add_items",
            "Setzt Einträge auf eine Liste (Einkaufsliste, Aufgaben, eigene Listen).",
            {"items": _ITEMS_PROP, "list": _LIST_PROP, "list_scope": _SCOPE_PROP, **_DATE_PROPS,
             "priority": {"type": "string", "enum": ["high", "normal", "low"]},
             "note": {"type": "string"}, "confirmed": _CONFIRMED_PROP},
            ["items"]),
        _fn("lists_query_items",
            "Zeigt/prüft Einträge: was steht auf einer Liste, was ist fällig/überfällig, Fristen, "
            "'steht X drauf?' (search), Anzahl (count_only), erledigte Einträge (done).",
            {"list": _LIST_PROP, "list_scope": _SCOPE_PROP, "range": _RANGE_PROP,
             "date": {"type": "string", "description": "Bei range=date: YYYY-MM-DD"},
             "date_to": {"type": "string", "description": "Optional bei range=date: letzter Tag"},
             "only_deadlines": {"type": "boolean", "description": "Nur Fristen"},
             "search": {"type": "string", "description": "Gesuchter Eintrag bei 'Steht X auf …?'"},
             "count_only": {"type": "boolean"},
             "done": {"type": "boolean", "description": "Erledigte statt offene Einträge"},
             "include_notes": {"type": "boolean", "description": "Nur wenn nach Notizen gefragt"}}),
        _fn("lists_complete_items", "Hakt Einträge ab („… ist erledigt“).",
            {"items": _ITEMS_PROP, "list": _LIST_PROP, "list_scope": _SCOPE_PROP, "item_ref": _REF_PROP}),
        _fn("lists_reopen_items", "Öffnet abgehakte Einträge wieder („Butter ist doch nicht da“).",
            {"items": _ITEMS_PROP, "list": _LIST_PROP, "list_scope": _SCOPE_PROP, "item_ref": _REF_PROP}),
        _fn("lists_update_item",
            "Ändert einen Eintrag: Titel, Notiz, Fälligkeit, Frist, Priorität oder Liste (verschieben). Nur die "
            "zu ändernden new_*/clear_*-Felder setzen.",
            {"item": {"type": "string", "description": "Titel des Eintrags wie genannt"}, "list": _LIST_PROP,
             "item_ref": _REF_PROP, "new_title": {"type": "string"}, "new_note": {"type": "string"},
             "new_due_date": {"type": "string"}, "new_due_time": {"type": "string"},
             "new_deadline_date": {"type": "string"}, "new_deadline_time": {"type": "string"},
             "new_priority": {"type": "string", "enum": ["high", "normal", "low"]},
             "new_list": {"type": "string", "description": "Zielliste beim Verschieben"},
             "clear_due": {"type": "boolean"}, "clear_deadline": {"type": "boolean"},
             "clear_note": {"type": "boolean"}, "confirmed": _CONFIRMED_PROP}),
        _fn("lists_remove_items",
            "Entfernt Einträge. Einkaufsliste: sofort. Andere Listen: liefert zuerst ein ticket und löscht NOCH "
            "NICHT.",
            {"items": _ITEMS_PROP, "list": _LIST_PROP, "list_scope": _SCOPE_PROP, "item_ref": _REF_PROP}),
        _fn("lists_confirm_delete",
            "Löscht nach einer Rückfrage den Eintrag bzw. die Liste. Nur im Turn NACH der Rückfrage, wenn der "
            "Nutzer ausdrücklich zugestimmt hat.",
            {"ticket": {"type": "string", "description": "ticket aus der Rückfrage"}}, ["ticket"]),
        _fn("lists_cleanup", "Entfernt alle erledigten Einträge einer Liste („Räume die Liste X auf“).",
            {"list": _LIST_PROP, "list_scope": _SCOPE_PROP}),
        _fn("lists_manage",
            "Listenverwaltung: create (anlegen, shared=true für gemeinsam), rename, delete (mit Rückfrage), "
            "set_default (Standardliste), set_shopping (zur Einkaufsliste machen), overview (welche Listen).",
            {"action": {"type": "string",
                        "enum": ["create", "rename", "delete", "set_default", "set_shopping", "overview"]},
             "name": {"type": "string", "description": "Listenname"},
             "new_name": {"type": "string", "description": "Neuer Name bei rename"},
             "shared": {"type": "boolean", "description": "Bei create: gemeinsame Liste"},
             "list_scope": _SCOPE_PROP},
            ["action"]),
        _fn("lists_agenda",
            "Allgemeine Tagesabfrage („Was steht morgen an?“): Termine und fällige Einträge/Fristen zusammen.",
            {"range": {"type": "string", "enum": list(_AGENDA_RANGES)},
             "date": {"type": "string", "description": "Bei range=date: YYYY-MM-DD"},
             "date_to": {"type": "string", "description": "Optional bei range=date: letzter Tag"}},
            ["range"]),
    ]
