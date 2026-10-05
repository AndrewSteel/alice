"""
Calendar agent logic (PROJ-87): what the chat tools and the settings tab do.

Tool results are dicts handed verbatim to the LLM:
  - real failures carry an "error" key (code) plus a German "message" hint;
    alice-chat-stream marks those tool calls as failed
  - questions back to the user carry a "status" (needs_calendar, ambiguous,
    needs_scope, confirm_past, not_found, confirm_delete) plus "instruction"
  - success carries status created / updated / deleted / ok and ONLY data that
    Google confirmed — never an optimistic echo of the request
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from . import db, google, tickets
from . import timeutil as tu
from .auth import Caller

logger = logging.getLogger("alice-calendar.agent")

VOICE_LIMIT = 5
CHAT_LIMIT = 50
MAX_CANDIDATES = 8
SEARCH_DAYS_BACK = 1
SEARCH_DAYS_AHEAD = 90
WRITABLE_ROLES = ("owner", "writer")
NON_GOOGLE_SCOPES = ("openid", "email", "profile")


@dataclass
class Ctx:
    caller: Caller
    client: httpx.AsyncClient
    tz_name: str
    tz: ZoneInfo
    now: datetime
    channel: str = "chat"             # "voice" | "chat"
    session_id: str | None = None
    turn: int | None = None
    _tokens: dict = field(default_factory=dict)

    async def token(self, connection_id: str) -> str:
        if connection_id not in self._tokens:
            self._tokens[connection_id] = await google.get_access_token(
                self.client, self.caller.token, connection_id
            )
        return self._tokens[connection_id]


@dataclass
class Cal:
    connection_id: str
    account: str
    calendar_id: str
    name: str
    color: str | None
    read_only: bool
    primary: bool
    is_default: bool


def _err(code: str, message: str, **extra) -> dict:
    return {"error": code, "message": message, **extra}


ERR_REAUTH = (
    "reauth_required",
    "Die Google-Verbindung muss erneuert werden. Sage dem Nutzer, dass er sie unter "
    "Einstellungen → Kalender neu verbinden muss. Nicht erneut versuchen.",
)
ERR_UNAVAILABLE = (
    "calendar_unavailable",
    "Der Kalender ist gerade nicht erreichbar. Sage dem Nutzer, er soll es später nochmal "
    "versuchen. Erfinde keine Termine und melde keinen Erfolg.",
)


# ---------------------------------------------------------------------------
# Loading the user's active calendars
# ---------------------------------------------------------------------------
async def load_active_calendars(ctx: Ctx) -> tuple[list[Cal], list[dict], bool]:
    """Return (calendars, warnings, any_selected).

    Connections without calendar scope are ignored; failing connections end up
    in warnings so the answer can mention them instead of silently omitting.
    Selected calendars that vanished in Google are skipped.
    """
    connections = await google.list_connections(ctx.client, ctx.caller.token)
    selections = [s for s in await db.list_selections(ctx.caller.user_id) if s["is_active"]]
    by_conn: dict[str, list[dict]] = {}
    for s in selections:
        by_conn.setdefault(s["connection_id"], []).append(s)

    async def _one(conn: dict) -> tuple[list[Cal], dict | None]:
        sels = by_conn.get(conn["id"]) or []
        if not sels or not google.has_calendar_scope(conn.get("scopes") or []):
            return [], None
        account = conn.get("google_account") or ""
        if conn.get("status") == "error":
            return [], {"account": account, "problem": "reauth_required"}
        try:
            token = await ctx.token(conn["id"])
            listing = {c["id"]: c for c in await google.list_calendars(ctx.client, token)}
        except google.ReauthRequired:
            return [], {"account": account, "problem": "reauth_required"}
        except (google.Unavailable, google.GoogleRejected, google.NotFound):
            return [], {"account": account, "problem": "unavailable"}
        cals = []
        for s in sels:
            entry = listing.get(s["calendar_id"])
            if not entry:
                continue
            cals.append(_to_cal(conn, entry, s["is_default"]))
        return cals, None

    results = await asyncio.gather(*[_one(c) for c in connections])
    cals: list[Cal] = []
    warnings: list[dict] = []
    for c, w in results:
        cals.extend(c)
        if w:
            warnings.append(w)
    return cals, warnings, bool(selections)


def _to_cal(conn: dict, entry: dict, is_default: bool) -> Cal:
    read_only = entry.get("accessRole") not in WRITABLE_ROLES
    return Cal(
        connection_id=conn["id"],
        account=conn.get("google_account") or "",
        calendar_id=entry["id"],
        name=entry.get("summaryOverride") or entry.get("summary") or entry["id"],
        color=entry.get("backgroundColor"),
        read_only=read_only,
        primary=bool(entry.get("primary")),
        is_default=bool(is_default and not read_only),
    )


def _no_calendar_result(warnings: list[dict], any_selected: bool) -> dict:
    if warnings and all(w["problem"] == "reauth_required" for w in warnings):
        return _err(*ERR_REAUTH, accounts=[w["account"] for w in warnings])
    if warnings:
        return _err(*ERR_UNAVAILABLE)
    return _err(
        "no_active_calendar",
        "Es ist kein Kalender für Alice aktiviert. Verweise den Nutzer auf "
        "Einstellungen → Kalender." if not any_selected else
        "Keiner der aktivierten Kalender ist mehr verfügbar. Verweise den Nutzer auf "
        "Einstellungen → Kalender.",
    )


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------
_STOPWORDS = {
    "termin", "termine", "der", "die", "das", "den", "dem", "des", "mit", "beim", "bei",
    "mein", "meine", "meinen", "meinem", "meiner", "von", "vom", "zum", "zur", "und",
    "the", "my", "appointment", "with", "event", "einen", "eine", "ein",
}


def _norm(s: str) -> str:
    s = (s or "").lower().replace("ß", "ss")
    return re.sub(r"[^\w\s]", " ", s)


def _tokens(query: str) -> list[str]:
    out = []
    for tok in _norm(query).split():
        if tok in _STOPWORDS:
            continue
        for suffix in ("termine", "termin", "kalender"):
            if tok.endswith(suffix) and len(tok) - len(suffix) >= 3:
                tok = tok[: -len(suffix)]
                break
        if len(tok) >= 3:
            out.append(tok)
    return out


def title_matches(query: str | None, title: str) -> bool:
    toks = _tokens(query or "")
    if not toks:
        return True
    norm_title = _norm(title)
    compact_title = norm_title.replace(" ", "")
    if all(t in norm_title or t in compact_title for t in toks):
        return True
    compact_query = "".join(toks)
    return bool(compact_title) and len(compact_title) >= 3 and compact_title in compact_query


def match_calendar(cals: list[Cal], name: str) -> list[Cal]:
    target = _tokens(name)
    if not target:
        return []
    exact = [c for c in cals if _tokens(c.name) == target]
    if exact:
        return exact
    return [c for c in cals if title_matches(name, c.name) or title_matches(c.name, name)]


# ---------------------------------------------------------------------------
# Event refs (opaque handle for candidates)
# ---------------------------------------------------------------------------
def encode_ref(cal: Cal, event_id: str) -> str:
    raw = json.dumps([cal.connection_id, cal.calendar_id, event_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_ref(ref: str) -> tuple[str, str, str]:
    try:
        raw = base64.urlsafe_b64decode(ref + "=" * (-len(ref) % 4))
        conn, cal, ev = json.loads(raw)
        return str(conn), str(cal), str(ev)
    except Exception:
        raise tu.InputError("event_ref ist ungültig")


# ---------------------------------------------------------------------------
# Output shaping
# ---------------------------------------------------------------------------
def describe_event(ev: dict, cal: Cal, tz: ZoneInfo, show_calendar: bool) -> dict:
    times = tu.parse_event_times(ev, tz)
    out = {"title": ev.get("summary") or "(ohne Titel)", **tu.describe_times(times)}
    if ev.get("location"):
        out["location"] = ev["location"]
    if show_calendar:
        out["calendar"] = cal.name
    if ev.get("recurringEventId") or ev.get("recurrence"):
        out["recurring"] = True
    return out


def describe_full(ev: dict, cal: Cal, tz: ZoneInfo) -> dict:
    """Confirmation view of a created/changed event (always names the calendar)."""
    out = describe_event(ev, cal, tz, show_calendar=True)
    if ev.get("description"):
        out["description"] = ev["description"][:300]
    overrides = ((ev.get("reminders") or {}).get("overrides")) or []
    if overrides:
        out["reminder_minutes"] = [o.get("minutes") for o in overrides]
    if ev.get("recurrence"):
        out["recurrence"] = [tu.describe_rrule(r) for r in ev["recurrence"]]
    return out


# ---------------------------------------------------------------------------
# Tool: list events
# ---------------------------------------------------------------------------
async def _fetch_events(
    ctx: Ctx, cals: list[Cal], start: datetime, end: datetime, max_results: int,
) -> tuple[list[tuple[Cal, dict]], list[dict]]:
    async def _one(cal: Cal):
        try:
            token = await ctx.token(cal.connection_id)
            evs = await google.list_events(
                ctx.client, token, cal.calendar_id,
                start.isoformat(), end.isoformat(), ctx.tz_name, max_results,
            )
            return [(cal, e) for e in evs], None
        except google.NotFound:
            return [], None  # calendar vanished — skip without failing
        except google.ReauthRequired:
            return [], {"account": cal.account, "problem": "reauth_required"}
        except (google.Unavailable, google.GoogleRejected):
            return [], {"account": cal.account, "problem": "unavailable"}

    results = await asyncio.gather(*[_one(c) for c in cals])
    items: list[tuple[Cal, dict]] = []
    warnings: list[dict] = []
    for evs, w in results:
        items.extend(evs)
        if w and w not in warnings:
            warnings.append(w)
    return items, warnings


def _sort_key(item: tuple[Cal, dict], tz: ZoneInfo):
    cal, ev = item
    t = tu.parse_event_times(ev, tz)
    return (t.start, not t.all_day, (ev.get("summary") or "").lower())


async def list_events(ctx: Ctx, args: dict) -> dict:
    rng = tu.resolve_range(args.get("range"), ctx.tz, ctx.now, args.get("date"), args.get("date_to"))
    cals, warnings, any_selected = await load_active_calendars(ctx)
    if not cals:
        return _no_calendar_result(warnings, any_selected)

    items, ev_warnings = await _fetch_events(
        ctx, cals, rng.start, rng.end, 10 if rng.next_only else 250,
    )
    warnings += [w for w in ev_warnings if w not in warnings]
    failed_accounts = {w["account"] for w in ev_warnings}
    if not items and failed_accounts and all(c.account in failed_accounts for c in cals):
        # Every account failed — never report "keine Termine" in that case.
        return _no_calendar_result(warnings, True)

    items.sort(key=lambda it: _sort_key(it, ctx.tz))
    if rng.next_only:
        upcoming = [it for it in items if tu.parse_event_times(it[1], ctx.tz).start >= ctx.now]
        if upcoming:
            first_start = tu.parse_event_times(upcoming[0][1], ctx.tz).start
            items = [it for it in upcoming if tu.parse_event_times(it[1], ctx.tz).start == first_start]
        else:
            items = []

    limit = VOICE_LIMIT if ctx.channel == "voice" else CHAT_LIMIT
    show_calendar = len(cals) > 1
    shown = items[:limit]
    result: dict = {
        "status": "ok",
        "range": {"from": rng.first_day.isoformat(), "to": rng.last_day.isoformat(),
                  "next_only": rng.next_only},
        "timezone": ctx.tz_name,
        "events": [describe_event(ev, cal, ctx.tz, show_calendar) for cal, ev in shown],
        "total": len(items),
        "remaining": max(0, len(items) - len(shown)),
    }
    if not items:
        result["instruction"] = "Es liegen keine Termine im Zeitraum vor — sage das klar."
    elif result["remaining"]:
        result["instruction"] = (
            f"Nenne nur die gezeigten Termine und erwähne, dass es {result['remaining']} weitere gibt."
            if ctx.channel == "voice" else
            f"Die Liste wurde auf {limit} Termine gekürzt — weise darauf hin."
        )
    if warnings:
        result["warnings"] = warnings
        result["warning_instruction"] = (
            "Mindestens ein Google-Konto war nicht abrufbar — weise den Nutzer darauf hin, dass "
            "die Liste unvollständig sein kann (bei reauth_required: unter Einstellungen → "
            "Kalender neu verbinden)."
        )
    return result


# ---------------------------------------------------------------------------
# Calendar choice for writes
# ---------------------------------------------------------------------------
def choose_calendar(cals: list[Cal], name: str | None) -> Cal | dict:
    writable = [c for c in cals if not c.read_only]
    options = [c.name for c in writable]
    if name and str(name).strip():
        matches = match_calendar(cals, str(name))
        if len(matches) == 1:
            if matches[0].read_only:
                return _err(
                    "read_only_calendar",
                    f"Der Kalender „{matches[0].name}“ ist schreibgeschützt — dort kann Alice keine "
                    "Termine anlegen oder ändern. Sage das dem Nutzer.",
                )
            return matches[0]
        return {
            "status": "needs_calendar",
            "reason": "ambiguous" if matches else "unknown",
            "options": [c.name for c in matches if not c.read_only] or options,
            "instruction": "Frage den Nutzer, welcher dieser Kalender gemeint ist, und rufe das "
                           "Tool danach mit dem gewählten Kalendernamen erneut auf.",
        }
    default = next((c for c in writable if c.is_default), None)
    if default:
        return default
    if not writable:
        return _err(
            "read_only_calendar",
            "Alle aktivierten Kalender sind schreibgeschützt. Der Nutzer muss unter "
            "Einstellungen → Kalender einen beschreibbaren Kalender aktivieren.",
        )
    return {
        "status": "needs_calendar",
        "reason": "no_default",
        "options": options,
        "instruction": "Es ist kein Standard-Kalender festgelegt. Frage den Nutzer, in welchen "
                       "Kalender der Termin soll, und rufe das Tool danach mit calendar erneut auf.",
    }


def _reminders(minutes) -> dict | None:
    if minutes is None or str(minutes).strip() == "":
        return None
    try:
        n = int(minutes)
    except (TypeError, ValueError):
        raise tu.InputError("reminder_minutes muss eine Zahl sein")
    if n < 0 or n > tu.MAX_REMINDER_MINUTES:
        raise tu.InputError(f"reminder_minutes muss zwischen 0 und {tu.MAX_REMINDER_MINUTES} liegen")
    return {"useDefault": False, "overrides": [{"method": "popup", "minutes": n}]}


def _int_arg(args: dict, key: str) -> int | None:
    v = args.get(key)
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise tu.InputError(f"{key} muss eine ganze Zahl sein")


def _str_arg(args: dict, key: str, max_len: int) -> str | None:
    v = args.get(key)
    if v is None:
        return None
    v = str(v).strip()
    if len(v) > max_len:
        raise tu.InputError(f"{key} ist zu lang (max {max_len} Zeichen)")
    return v


# ---------------------------------------------------------------------------
# Tool: create event
# ---------------------------------------------------------------------------
async def create_event(ctx: Ctx, args: dict) -> dict:
    title = _str_arg(args, "title", 300)
    if not title:
        raise tu.InputError("title ist erforderlich")
    day = tu.parse_date(args.get("date"), "date")
    if day is None:
        raise tu.InputError("date ist erforderlich (YYYY-MM-DD)")
    start_time = tu.parse_time(args.get("start_time"), "start_time")
    end_time = tu.parse_time(args.get("end_time"), "end_time")
    end_day = tu.parse_date(args.get("end_date"), "end_date")
    duration = _int_arg(args, "duration_minutes")
    if args.get("all_day") is True:
        start_time = end_time = None
        duration = None
    if start_time is None and (end_time is not None):
        raise tu.InputError("end_time ohne start_time ist nicht möglich")

    g_start, g_end, times = tu.build_times(
        ctx.tz, ctx.tz_name, day, start_time, end_time, duration, end_day,
    )

    recurrence = args.get("recurrence")
    rrule = None
    if recurrence:
        rrule, weekday_idx = tu.build_rrule(recurrence, ctx.tz, times)
        aligned = tu.align_to_weekdays(times, weekday_idx)
        if aligned is not times:
            times = aligned
            g_start, g_end = tu.times_to_google(times, ctx.tz_name)

    if tu.is_in_past(times, ctx.now) and args.get("confirm_past") is not True:
        return {
            "status": "confirm_past",
            "event": {"title": title, **tu.describe_times(times)},
            "instruction": "Der Termin läge in der Vergangenheit. Frage den Nutzer, ob er ihn "
                           "wirklich so anlegen möchte (oder ob ein anderes Datum gemeint ist). "
                           "Nur nach Bestätigung erneut mit confirm_past=true aufrufen.",
        }

    cals, warnings, any_selected = await load_active_calendars(ctx)
    if not cals:
        return _no_calendar_result(warnings, any_selected)
    chosen = choose_calendar(cals, args.get("calendar"))
    if isinstance(chosen, dict):
        return chosen

    body: dict = {"summary": title, "start": g_start, "end": g_end}
    location = _str_arg(args, "location", 500)
    description = _str_arg(args, "description", 4000)
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    reminders = _reminders(args.get("reminder_minutes"))
    if reminders:
        body["reminders"] = reminders
    if rrule:
        body["recurrence"] = [rrule]

    try:
        token = await ctx.token(chosen.connection_id)
        created = await google.insert_event(ctx.client, token, chosen.calendar_id, body)
    except google.ReauthRequired:
        return _err(*ERR_REAUTH)
    except google.GoogleRejected as exc:
        return _err("google_rejected", f"Google hat das Anlegen abgelehnt ({exc.status}). Melde "
                                       "dem Nutzer, dass der Termin NICHT angelegt wurde.")
    except (google.Unavailable, google.NotFound):
        return _err(*ERR_UNAVAILABLE)

    return {
        "status": "created",
        "event": describe_full(created, chosen, ctx.tz),
        "instruction": "Bestätige in EINEM kurzen Satz Titel, Tag, Uhrzeit und Kalender wie hier "
                       "angegeben (damit Hörfehler auffallen). Keine weiteren Rückfragen.",
    }


# ---------------------------------------------------------------------------
# Identifying an existing event (update / delete)
# ---------------------------------------------------------------------------
@dataclass
class Target:
    cal: Cal
    event: dict          # the occurrence (or single event) the user referred to


async def _identify(ctx: Ctx, cals: list[Cal], args: dict) -> Target | dict:
    ref = args.get("event_ref")
    if ref:
        conn_id, cal_id, ev_id = decode_ref(str(ref))
        cal = next((c for c in cals if c.connection_id == conn_id and c.calendar_id == cal_id), None)
        if cal is None:
            return {"status": "not_found", "instruction": "Der Termin wurde nicht gefunden. Sage das dem Nutzer."}
        try:
            ev = await google.get_event(ctx.client, await ctx.token(conn_id), cal_id, ev_id)
        except google.NotFound:
            return {"status": "not_found",
                    "instruction": "Der Termin existiert nicht mehr (evtl. in Google gelöscht). Sage das dem Nutzer."}
        return Target(cal, ev)

    query = _str_arg(args, "title_query", 200) or ""
    day = tu.parse_date(args.get("date"), "date")
    at = tu.parse_time(args.get("time"), "time")
    if not query and day is None:
        raise tu.InputError("title_query oder date wird benötigt, um den Termin zu finden")

    if day is not None:
        start = tu.local_midnight(day, ctx.tz)
        end = tu.local_midnight(day + timedelta(days=1), ctx.tz)
    else:
        today = ctx.now.astimezone(ctx.tz).date()
        start = tu.local_midnight(today - timedelta(days=SEARCH_DAYS_BACK), ctx.tz)
        end = tu.local_midnight(today + timedelta(days=SEARCH_DAYS_AHEAD), ctx.tz)

    items, warnings = await _fetch_events(ctx, cals, start, end, 250)
    if not items and warnings:
        return _no_calendar_result(warnings, True)

    cands = []
    for cal, ev in items:
        if not title_matches(query, ev.get("summary") or ""):
            continue
        if at is not None:
            t = tu.parse_event_times(ev, ctx.tz)
            if t.all_day or t.start.time().replace(second=0) != at:
                continue
        cands.append((cal, ev))
    cands.sort(key=lambda it: _sort_key(it, ctx.tz))

    if not cands:
        res = {"status": "not_found",
               "instruction": "Kein passender Termin gefunden. Sage das dem Nutzer, rate nicht."}
        if warnings:
            res["warnings"] = warnings
        return res
    if len(cands) == 1:
        return Target(*cands[0])

    # Several occurrences of ONE series and no date given → the next upcoming
    # occurrence stands for the series (the scope question follows anyway).
    series_keys = {(c.connection_id, c.calendar_id, e.get("recurringEventId")) for c, e in cands}
    if len(series_keys) == 1 and next(iter(series_keys))[2] and day is None:
        upcoming = [it for it in cands if tu.parse_event_times(it[1], ctx.tz).end >= ctx.now]
        return Target(*(upcoming or cands)[0])

    show_calendar = len(cals) > 1
    return {
        "status": "ambiguous",
        "candidates": [
            {"event_ref": encode_ref(cal, ev["id"]), **describe_event(ev, cal, ctx.tz, show_calendar)}
            for cal, ev in cands[:MAX_CANDIDATES]
        ],
        "more": max(0, len(cands) - MAX_CANDIDATES),
        "instruction": "Mehrere Termine passen. Nenne sie knapp (Titel, Tag, Uhrzeit) und frage, welcher "
                       "gemeint ist. Danach das Tool mit dem event_ref des gewählten Termins erneut aufrufen.",
    }


def _needs_scope(target: Target, ctx: Ctx, action: str) -> dict:
    return {
        "status": "needs_scope",
        "event": {"event_ref": encode_ref(target.cal, target.event["id"]),
                  **describe_event(target.event, target.cal, ctx.tz, True)},
        "instruction": f"Der Termin gehört zu einer Serie. Frage kurz: „Nur diesen Termin oder die "
                       f"ganze Serie {action}?“ Nach der Antwort erneut mit event_ref und scope "
                       f"(single = nur dieser, series = ganze Serie) aufrufen.",
    }


def _scope(args: dict) -> str | None:
    s = str(args.get("scope") or "").strip().lower()
    if s in ("single", "series"):
        return s
    if s:
        raise tu.InputError("scope muss 'single' oder 'series' sein")
    return None


# ---------------------------------------------------------------------------
# Tool: update event
# ---------------------------------------------------------------------------
_CHANGE_KEYS = (
    "new_title", "new_date", "new_start_time", "new_end_time", "new_duration_minutes",
    "new_all_day", "new_location", "new_description", "new_reminder_minutes", "new_calendar",
)


async def update_event(ctx: Ctx, args: dict) -> dict:
    if not any(args.get(k) not in (None, "") for k in _CHANGE_KEYS):
        raise tu.InputError("Es wurde keine Änderung angegeben (new_* Felder)")
    scope = _scope(args)

    cals, warnings, any_selected = await load_active_calendars(ctx)
    if not cals:
        return _no_calendar_result(warnings, any_selected)
    try:
        target = await _identify(ctx, cals, args)
    except google.ReauthRequired:
        return _err(*ERR_REAUTH)
    except (google.Unavailable, google.GoogleRejected):
        return _err(*ERR_UNAVAILABLE)
    if isinstance(target, dict):
        return target

    ev = target.event
    is_series = bool(ev.get("recurringEventId"))
    if is_series and scope is None:
        return _needs_scope(target, ctx, "ändern")
    if target.cal.read_only:
        return _err("read_only_calendar",
                    f"Der Kalender „{target.cal.name}“ ist schreibgeschützt — der Termin kann nicht "
                    "geändert werden.")

    series = is_series and scope == "series"
    try:
        token = await ctx.token(target.cal.connection_id)
        edit_id = ev["recurringEventId"] if series else ev["id"]
        base_ev = await google.get_event(ctx.client, token, target.cal.calendar_id, edit_id) if series else ev

        body: dict = {}
        for key, field_name, max_len in (("new_title", "summary", 300),
                                         ("new_location", "location", 500),
                                         ("new_description", "description", 4000)):
            v = _str_arg(args, key, max_len)
            if v is not None:
                body[field_name] = v
        reminders = _reminders(args.get("new_reminder_minutes"))
        if reminders:
            body["reminders"] = reminders

        if any(args.get(k) not in (None, "") for k in
               ("new_date", "new_start_time", "new_end_time", "new_duration_minutes", "new_all_day")):
            body.update(_time_patch(ctx, args, ev, base_ev, series))

        # Calendar change
        dest = None
        if args.get("new_calendar"):
            chosen = choose_calendar(cals, args.get("new_calendar"))
            if isinstance(chosen, dict):
                return chosen
            if (chosen.connection_id, chosen.calendar_id) != (target.cal.connection_id, target.cal.calendar_id):
                dest = chosen
                if is_series and not series:
                    raise tu.InputError("Ein einzelner Serientermin kann nicht in einen anderen Kalender "
                                        "verschoben werden — nur die ganze Serie")
                if dest.connection_id != target.cal.connection_id and (series or base_ev.get("recurrence")):
                    raise tu.InputError("Serien können nicht in einen Kalender eines anderen Google-Kontos "
                                        "verschoben werden")

        final_cal = target.cal
        if body:
            updated = await google.patch_event(ctx.client, token, target.cal.calendar_id, edit_id, body)
        else:
            updated = base_ev

        if dest is not None:
            if dest.connection_id == target.cal.connection_id:
                updated = await google.move_event(ctx.client, token, target.cal.calendar_id, edit_id,
                                                  dest.calendar_id)
            else:
                updated = await _copy_to_other_account(ctx, updated, target.cal, dest, edit_id, token)
            final_cal = dest
    except google.NotFound:
        return {"status": "not_found",
                "instruction": "Der Termin existiert nicht mehr (evtl. gerade in Google gelöscht). "
                               "Sage das dem Nutzer; es wurde nichts geändert."}
    except google.ReauthRequired:
        return _err(*ERR_REAUTH)
    except google.GoogleRejected as exc:
        return _err("google_rejected", f"Google hat die Änderung abgelehnt ({exc.status}). Melde dem "
                                       "Nutzer, dass NICHTS geändert wurde.")
    except google.Unavailable:
        return _err(*ERR_UNAVAILABLE)

    return {
        "status": "updated",
        "scope": "series" if series else "single",
        "event": describe_full(updated, final_cal, ctx.tz),
        "instruction": "Bestätige in EINEM kurzen Satz die neue Fassung (Titel, Tag, Uhrzeit) wie hier "
                       "angegeben.",
    }


def _time_patch(ctx: Ctx, args: dict, occurrence: dict, base_ev: dict, series: bool) -> dict:
    occ_t = tu.parse_event_times(occurrence, ctx.tz)
    new_all_day = args.get("new_all_day")
    new_all_day = bool(new_all_day) if isinstance(new_all_day, bool) else None
    new_occ = tu.apply_time_change(
        occ_t, ctx.tz,
        new_day=tu.parse_date(args.get("new_date"), "new_date"),
        new_start_time=tu.parse_time(args.get("new_start_time"), "new_start_time"),
        new_end_time=tu.parse_time(args.get("new_end_time"), "new_end_time"),
        duration_minutes=_int_arg(args, "new_duration_minutes"),
        all_day=new_all_day,
    )
    if not series:
        start, end = tu.times_to_google(new_occ, ctx.tz_name)
        return {"start": start, "end": end}

    # Whole series: only time of day / duration — the date pattern lives in
    # the RRULE (BYDAY etc.) and moving DTSTART would break it.
    if args.get("new_date"):
        raise tu.InputError("Bei der ganzen Serie können nur Uhrzeit und Dauer geändert werden, nicht "
                            "das Datum. Für ein anderes Datum nur diesen Termin ändern oder Google nutzen.")
    if new_occ.all_day != occ_t.all_day:
        raise tu.InputError("Eine Serie kann nicht zwischen ganztägig und mit Uhrzeit umgestellt werden")
    master_t = tu.parse_event_times(base_ev, ctx.tz)
    if master_t.all_day:
        raise tu.InputError("Bei ganztägigen Serien gibt es keine Uhrzeit zu ändern")
    master_start = datetime.combine(master_t.start.date(), new_occ.start.timetz().replace(tzinfo=None),
                                    tzinfo=ctx.tz)
    new_master = tu.EventTimes(master_start, master_start + (new_occ.end - new_occ.start), False)
    start, end = tu.times_to_google(new_master, ctx.tz_name)
    return {"start": start, "end": end}


async def _copy_to_other_account(ctx: Ctx, ev: dict, src: Cal, dest: Cal, src_id: str, src_token: str) -> dict:
    """Cross-account calendar change for a single event: insert copy, delete original."""
    body = {k: ev[k] for k in ("summary", "location", "description", "start", "end", "reminders") if k in ev}
    dest_token = await ctx.token(dest.connection_id)
    created = await google.insert_event(ctx.client, dest_token, dest.calendar_id, body)
    try:
        await google.delete_event(ctx.client, src_token, src.calendar_id, src_id)
    except google.NotFound:
        pass
    return created


# ---------------------------------------------------------------------------
# Tool: delete (stage 1: prepare → ticket; stage 2: confirm)
# ---------------------------------------------------------------------------
async def prepare_delete(ctx: Ctx, args: dict) -> dict:
    if not ctx.session_id or ctx.turn is None:
        return _err("no_session", "Löschen ist nur innerhalb eines Gesprächs möglich.")
    scope = _scope(args)
    cals, warnings, any_selected = await load_active_calendars(ctx)
    if not cals:
        return _no_calendar_result(warnings, any_selected)
    try:
        target = await _identify(ctx, cals, args)
    except google.ReauthRequired:
        return _err(*ERR_REAUTH)
    except (google.Unavailable, google.GoogleRejected):
        return _err(*ERR_UNAVAILABLE)
    if isinstance(target, dict):
        return target

    ev = target.event
    is_series = bool(ev.get("recurringEventId"))
    if is_series and scope is None:
        return _needs_scope(target, ctx, "löschen")
    if target.cal.read_only:
        return _err("read_only_calendar",
                    f"Der Kalender „{target.cal.name}“ ist schreibgeschützt — der Termin kann nicht "
                    "gelöscht werden.")

    series = is_series and scope == "series"
    try:
        if series:
            token = await ctx.token(target.cal.connection_id)
            master = await google.get_event(ctx.client, token, target.cal.calendar_id, ev["recurringEventId"])
            delete_id, etag = master["id"], master.get("etag")
        else:
            delete_id, etag = ev["id"], ev.get("etag")
    except google.NotFound:
        return {"status": "not_found", "instruction": "Die Serie existiert nicht mehr. Sage das dem Nutzer."}
    except google.ReauthRequired:
        return _err(*ERR_REAUTH)
    except (google.Unavailable, google.GoogleRejected):
        return _err(*ERR_UNAVAILABLE)

    described = describe_event(ev, target.cal, ctx.tz, True)
    ticket = await tickets.issue(ctx.caller.user_id, ctx.session_id, ctx.turn, {
        "connection_id": target.cal.connection_id,
        "calendar_id": target.cal.calendar_id,
        "event_id": delete_id,
        "etag": etag,
        "scope": "series" if series else "single",
        "event": described,
    })
    return {
        "status": "confirm_delete",
        "ticket": ticket,
        "scope": "series" if series else "single",
        "event": described,
        "instruction": "NOCH NICHTS GELÖSCHT. Frage in EINEM kurzen Satz, ob der Termin (Titel, Tag, "
                       "Uhrzeit" + (", ganze Serie" if series else "") + ") gelöscht werden soll — ohne "
                       "Erklärung des Ablaufs. calendar_confirm_delete erst nach dem Ja des Nutzers in "
                       "seiner nächsten Nachricht.",
    }


_TICKET_MESSAGES = {
    "same_turn": "Die Löschung braucht die ausdrückliche Zustimmung des Nutzers in seiner nächsten "
                 "Nachricht. Frage ihn jetzt und warte auf seine Antwort. Es wurde NICHTS gelöscht.",
    "expired": "Die Löschanfrage ist verfallen (es kam zwischendurch eine andere Nachricht). Es wurde "
               "NICHTS gelöscht. Bei Bedarf neu mit calendar_delete_event beginnen.",
    "unknown": "Unbekanntes oder abgelaufenes Lösch-Ticket. Es wurde NICHTS gelöscht. Bei Bedarf neu "
               "mit calendar_delete_event beginnen.",
    "wrong_owner": "Ungültiges Lösch-Ticket. Es wurde NICHTS gelöscht.",
}


async def confirm_delete(ctx: Ctx, args: dict) -> dict:
    if not ctx.session_id or ctx.turn is None:
        return _err("no_session", "Löschen ist nur innerhalb eines Gesprächs möglich.")
    try:
        target = await tickets.redeem(str(args.get("ticket") or ""), ctx.caller.user_id,
                                      ctx.session_id, ctx.turn)
    except tickets.TicketError as exc:
        return _err(f"ticket_{exc.reason}", _TICKET_MESSAGES.get(exc.reason, _TICKET_MESSAGES["unknown"]))

    conn_id, cal_id, ev_id = target["connection_id"], target["calendar_id"], target["event_id"]
    # The calendar must still be selected (permission may have changed in between).
    selected = {(s["connection_id"], s["calendar_id"]) for s in await db.list_selections(ctx.caller.user_id)
                if s["is_active"]}
    if (conn_id, cal_id) not in selected:
        return _err("calendar_not_active", "Der Kalender ist nicht mehr für Alice aktiviert. Es wurde "
                                           "NICHTS gelöscht.")
    try:
        token = await ctx.token(conn_id)
        current = await google.get_event(ctx.client, token, cal_id, ev_id)
        if target.get("etag") and current.get("etag") != target["etag"]:
            return _err("event_changed", "Der Termin wurde zwischenzeitlich in Google geändert. Es wurde "
                                         "NICHTS gelöscht. Sage das dem Nutzer.")
        await google.delete_event(ctx.client, token, cal_id, ev_id)
    except google.NotFound:
        return _err("event_gone", "Der Termin existiert nicht mehr (bereits in Google gelöscht). Sage "
                                  "das dem Nutzer.")
    except google.ReauthRequired:
        return _err(*ERR_REAUTH)
    except google.GoogleRejected as exc:
        return _err("google_rejected", f"Google hat das Löschen abgelehnt ({exc.status}). Es wurde "
                                       "NICHTS gelöscht.")
    except google.Unavailable:
        return _err(*ERR_UNAVAILABLE)

    return {
        "status": "deleted",
        "scope": target.get("scope"),
        "event": target.get("event"),
        "instruction": "Bestätige dem Nutzer kurz, dass der Termin gelöscht wurde.",
    }


# ---------------------------------------------------------------------------
# Settings tab
# ---------------------------------------------------------------------------
async def accounts_overview(ctx: Ctx) -> dict:
    connections = await google.list_connections(ctx.client, ctx.caller.token)
    selections = await db.list_selections(ctx.caller.user_id)
    sel_by_conn: dict[str, dict[str, dict]] = {}
    for s in selections:
        sel_by_conn.setdefault(s["connection_id"], {})[s["calendar_id"]] = s

    async def _one(conn: dict) -> dict:
        scopes = conn.get("scopes") or []
        has_scope = google.has_calendar_scope(scopes)
        other_scopes = [s for s in scopes
                        if s not in google.CALENDAR_SCOPES and s not in NON_GOOGLE_SCOPES
                        and "userinfo" not in s]
        out = {
            "connection_id": conn["id"],
            "google_account": conn.get("google_account"),
            "status": conn.get("status"),
            "has_calendar_scope": has_scope,
            "has_other_scopes": bool(other_scopes),
            "calendars": None,
            "calendars_error": None,
        }
        if not has_scope:
            return out
        if conn.get("status") == "error":
            out["calendars_error"] = "reauth_required"
            return out
        try:
            token = await ctx.token(conn["id"])
            listing = await google.list_calendars(ctx.client, token)
        except google.ReauthRequired:
            out["status"] = "error"
            out["calendars_error"] = "reauth_required"
            return out
        except (google.Unavailable, google.GoogleRejected, google.NotFound):
            out["calendars_error"] = "unavailable"
            return out

        conn_sels = sel_by_conn.get(conn["id"], {})
        present = {c["id"] for c in listing}
        stale = [cid for cid in conn_sels if cid not in present]
        if stale:
            await db.delete_selections(ctx.caller.user_id, conn["id"], stale)
        calendars = []
        for entry in listing:
            sel = conn_sels.get(entry["id"])
            cal = _to_cal(conn, entry, bool(sel and sel["is_default"]))
            if sel and sel["is_default"] and cal.read_only:
                await db.clear_default(ctx.caller.user_id, conn["id"], entry["id"])
            calendars.append({
                "id": cal.calendar_id,
                "name": cal.name,
                "color": cal.color,
                "read_only": cal.read_only,
                "primary": cal.primary,
                "is_active": bool(sel and sel["is_active"]),
                "is_default": cal.is_default,
            })
        calendars.sort(key=lambda c: (not c["primary"], c["name"].lower()))
        out["calendars"] = calendars
        return out

    accounts = await asyncio.gather(*[_one(c) for c in connections])
    return {"required_scopes": google.CALENDAR_SCOPES, "accounts": list(accounts)}


class SelectionError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


async def update_selection(ctx: Ctx, connection_id: str, calendar_id: str,
                           is_active: bool | None, is_default: bool | None) -> list[dict]:
    connections = await google.list_connections(ctx.client, ctx.caller.token)
    conn = next((c for c in connections if c["id"] == connection_id), None)
    if conn is None:
        raise SelectionError(404, "Konto nicht gefunden")
    if not google.has_calendar_scope(conn.get("scopes") or []):
        raise SelectionError(409, "Für dieses Konto ist der Kalender-Zugriff nicht freigegeben")
    try:
        token = await ctx.token(connection_id)
        listing = {c["id"]: c for c in await google.list_calendars(ctx.client, token)}
    except google.ReauthRequired:
        raise SelectionError(409, "reauth_required")
    except (google.Unavailable, google.GoogleRejected, google.NotFound):
        raise SelectionError(502, "Google ist gerade nicht erreichbar")
    entry = listing.get(calendar_id)
    if entry is None:
        raise SelectionError(404, "Kalender nicht gefunden")
    writable = entry.get("accessRole") in WRITABLE_ROLES
    try:
        await db.set_selection(ctx.caller.user_id, connection_id, calendar_id, is_active, is_default, writable)
    except ValueError as exc:
        raise SelectionError(400, str(exc))
    return await db.list_selections(ctx.caller.user_id)
