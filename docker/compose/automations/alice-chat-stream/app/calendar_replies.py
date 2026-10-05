"""
PROJ-87 — deterministic replies for calendar tool results.

Live tests showed the deployed model ignores brevity rules: it read out the
request again, asked "nur diesen oder die ganze Serie?" for a single event and
confirmed a deletion twice. Calendar outcomes are therefore phrased here from
the structured alice-calendar result instead of by the LLM — short, always
consistent with what Google confirmed, and in the user's language (de / en,
the languages Alice supports; anything else falls back to German like the LLM
language instruction does).

compose() returns None for results the LLM must handle itself (invalid input
it can correct, an internal "await the user" guard).
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Berlin")

# Statuses after which the turn is finished (voice session may end).
TERMINAL_STATUSES = {"created", "updated", "deleted", "ok", "not_found"}

_WEEKDAYS = {
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
_MONTHS = {
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
           "Oktober", "November", "Dezember"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
}

_ERRORS = {
    "de": {
        "reauth_required": "Die Verbindung zu Google muss erneuert werden – bitte unter Einstellungen → Kalender neu verbinden.",
        "calendar_unavailable": "Der Kalender ist gerade nicht erreichbar. Bitte versuch es später noch einmal.",
        "timeout": "Der Kalender hat nicht rechtzeitig geantwortet. Bitte versuch es später noch einmal.",
        "no_active_calendar": "Es ist noch kein Kalender für mich freigegeben – das geht unter Einstellungen → Kalender.",
        "read_only_calendar": "Dieser Kalender ist schreibgeschützt, dort kann ich nichts eintragen oder ändern.",
        "unsupported_recurrence": "So eine Wiederholung kann ich nicht anlegen – bitte richte sie direkt in Google Kalender ein.",
        "forbidden": "Deine Rolle hat keinen Zugriff auf den Kalender.",
        "unknown_speaker": "Ich habe dich nicht erkannt und weiß deshalb nicht, wessen Kalender gemeint ist.",
        "calendar_disabled": "Der Kalender ist für dich nicht verfügbar.",
        "ticket_expired": "Die Löschanfrage ist abgelaufen, ich habe nichts gelöscht. Sag mir einfach noch einmal, welchen Termin ich löschen soll.",
        "ticket_unknown": "Die Löschanfrage ist abgelaufen, ich habe nichts gelöscht. Sag mir einfach noch einmal, welchen Termin ich löschen soll.",
        "ticket_wrong_owner": "Ich habe nichts gelöscht.",
        "event_changed": "Der Termin wurde inzwischen geändert, deshalb habe ich ihn nicht gelöscht.",
        "event_gone": "Diesen Termin gibt es nicht mehr.",
        "calendar_not_active": "Der Kalender ist nicht mehr freigegeben, ich habe nichts gelöscht.",
        "google_rejected": "Google hat das abgelehnt, es wurde nichts geändert.",
        "internal_error": "Da ist etwas schiefgegangen, es wurde nichts geändert. Bitte versuch es später noch einmal.",
        "no_session": "Das geht nur innerhalb eines Gesprächs.",
    },
    "en": {
        "reauth_required": "The Google connection needs to be renewed – please reconnect under Settings → Calendar.",
        "calendar_unavailable": "The calendar is not reachable right now. Please try again later.",
        "timeout": "The calendar did not answer in time. Please try again later.",
        "no_active_calendar": "No calendar has been enabled for me yet – you can do that under Settings → Calendar.",
        "read_only_calendar": "That calendar is read-only, I can't add or change anything there.",
        "unsupported_recurrence": "I can't create that kind of repetition – please set it up directly in Google Calendar.",
        "forbidden": "Your role has no access to the calendar.",
        "unknown_speaker": "I didn't recognise you, so I don't know whose calendar you mean.",
        "calendar_disabled": "The calendar is not available for you.",
        "ticket_expired": "The delete request has expired, nothing was deleted. Just tell me again which event to delete.",
        "ticket_unknown": "The delete request has expired, nothing was deleted. Just tell me again which event to delete.",
        "ticket_wrong_owner": "Nothing was deleted.",
        "event_changed": "The event has changed in the meantime, so I did not delete it.",
        "event_gone": "That event no longer exists.",
        "calendar_not_active": "That calendar is no longer enabled, nothing was deleted.",
        "google_rejected": "Google rejected that, nothing was changed.",
        "internal_error": "Something went wrong, nothing was changed. Please try again later.",
        "no_session": "That only works within a conversation.",
    },
}

# Left to the LLM: it can fix its own call or must ask the user.
_LLM_HANDLED_ERRORS = {"invalid_input", "await_user_answer", "ticket_same_turn"}


def language(sprache: str | None) -> str:
    s = (sprache or "").lower()
    return "en" if s in ("en", "englisch", "english") else "de"


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
def _time(hhmm: str | None, lang: str, voice: bool) -> str:
    if not hhmm:
        return ""
    h, m = (int(x) for x in hhmm.split(":"))
    if lang == "de":
        if voice:
            return f"{h} Uhr" if m == 0 else f"{h} Uhr {m}"
        return f"{h}:{m:02d} Uhr"
    return f"{h}:{m:02d}"


def _day(d: date, lang: str, today: date) -> str:
    """'heute' / 'morgen' / 'übermorgen' / 'am Dienstag, 13. Oktober'."""
    delta = (d - today).days
    if lang == "de":
        rel = {0: "heute", 1: "morgen", 2: "übermorgen", -1: "gestern"}.get(delta)
        if rel:
            return rel
        return f"am {_WEEKDAYS['de'][d.weekday()]}, {d.day}. {_MONTHS['de'][d.month - 1]}"
    rel = {0: "today", 1: "tomorrow", -1: "yesterday"}.get(delta)
    if rel:
        return rel
    return f"on {_WEEKDAYS['en'][d.weekday()]}, {_MONTHS['en'][d.month - 1]} {d.day}"


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _when(ev: dict, lang: str, voice: bool, today: date, with_day: bool = True) -> str:
    """'morgen um 10 Uhr' / 'morgen, ganztägig' / 'vom 12. bis 16. Oktober'."""
    d = _parse_day(ev.get("date"))
    day = _day(d, lang, today) if (d and with_day) else ""
    if ev.get("all_day"):
        end = _parse_day(ev.get("end_date"))
        if end and d and end > d:
            if lang == "de":
                return f"von {_day(d, lang, today).removeprefix('am ')} bis {_day(end, lang, today).removeprefix('am ')}"
            return f"from {_day(d, lang, today).removeprefix('on ')} to {_day(end, lang, today).removeprefix('on ')}"
        tag = "ganztägig" if lang == "de" else "all day"
        return f"{day}, {tag}".strip(", ") if day else tag
    t = _time(ev.get("start_time"), lang, voice)
    at = (f"um {t}" if lang == "de" else f"at {t}") if t else ""
    return " ".join(x for x in (day, at) if x)


def _title(ev: dict, lang: str) -> str:
    title = ev.get("title") or ("Termin" if lang == "de" else "event")
    return f"„{title}“" if lang == "de" else f"“{title}”"


def _join(items: list[str], lang: str, last: str | None = None) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    word = last or ("und" if lang == "de" else "and")
    return ", ".join(items[:-1]) + f" {word} " + items[-1]


# ---------------------------------------------------------------------------
# Per-status replies
# ---------------------------------------------------------------------------
def _created(r: dict, lang: str, voice: bool, today: date) -> str:
    ev = r.get("event") or {}
    cal = ev.get("calendar")
    extra = ""
    if ev.get("recurrence"):
        extra += " (wiederkehrend)" if lang == "de" else " (recurring)"
    if lang == "de":
        where = f" in den Kalender „{cal}“" if cal else ""
        return f"Ich habe {_title(ev, lang)} {_when(ev, lang, voice, today)}{where} eingetragen{extra}."
    where = f" to the calendar “{cal}”" if cal else ""
    return f"I added {_title(ev, lang)} {_when(ev, lang, voice, today)}{where}{extra}."


def _updated(r: dict, lang: str, voice: bool, today: date) -> str:
    ev = r.get("event") or {}
    series = r.get("scope") == "series"
    if lang == "de":
        what = "die Serie " if series else ""
        return f"Ich habe {what}{_title(ev, lang)} geändert, jetzt {_when(ev, lang, voice, today)}."
    what = "the series " if series else ""
    return f"I changed {what}{_title(ev, lang)}, now {_when(ev, lang, voice, today)}."


def _deleted(r: dict, lang: str) -> str:
    ev = r.get("event") or {}
    if lang == "de":
        return (f"Ich habe die Serie {_title(ev, lang)} gelöscht." if r.get("scope") == "series"
                else f"Ich habe den Termin {_title(ev, lang)} gelöscht.")
    return (f"I deleted the series {_title(ev, lang)}." if r.get("scope") == "series"
            else f"I deleted {_title(ev, lang)}.")


def _confirm_delete(r: dict, lang: str, voice: bool, today: date) -> str:
    ev = r.get("event") or {}
    if lang == "de":
        if r.get("scope") == "series":
            return f"Soll ich die ganze Serie {_title(ev, lang)} löschen?"
        return f"Soll ich {_title(ev, lang)} {_when(ev, lang, voice, today)} löschen?"
    if r.get("scope") == "series":
        return f"Shall I delete the whole series {_title(ev, lang)}?"
    return f"Shall I delete {_title(ev, lang)} {_when(ev, lang, voice, today)}?"


def _needs_scope(r: dict, lang: str, voice: bool, today: date) -> str:
    ev = r.get("event") or {}
    if lang == "de":
        return f"{_title(ev, lang)} {_when(ev, lang, voice, today)} ist ein Serientermin. Nur diesen Termin oder die ganze Serie?"
    return f"{_title(ev, lang)} {_when(ev, lang, voice, today)} is a recurring event. Just this one or the whole series?"


def _ambiguous(r: dict, lang: str, voice: bool, today: date) -> str:
    cands = r.get("candidates") or []
    if voice:
        cands = cands[:3]  # read aloud: keep the choice short
    items = [f"{_title(c, lang)} {_when(c, lang, voice, today)}" for c in cands]
    if lang == "de":
        return f"Welchen Termin meinst du: {_join(items, lang, 'oder')}?"
    return f"Which event do you mean: {_join(items, lang, 'or')}?"


def _needs_calendar(r: dict, lang: str) -> str:
    opts = [f"„{o}“" if lang == "de" else f"“{o}”" for o in (r.get("options") or [])]
    if lang == "de":
        lead = "Diesen Kalender kenne ich nicht. " if r.get("reason") == "unknown" else ""
        return f"{lead}In welchen Kalender soll der Termin: {_join(opts, lang, 'oder')}?"
    lead = "I don't know that calendar. " if r.get("reason") == "unknown" else ""
    return f"{lead}Which calendar should it go to: {_join(opts, lang, 'or')}?"


def _confirm_past(r: dict, lang: str, voice: bool, today: date) -> str:
    ev = r.get("event") or {}
    if lang == "de":
        return f"{_title(ev, lang)} {_when(ev, lang, voice, today)} liegt in der Vergangenheit. Soll ich den Termin trotzdem eintragen?"
    return f"{_title(ev, lang)} {_when(ev, lang, voice, today)} is in the past. Shall I add it anyway?"


def _range_phrase(rng: dict, lang: str, today: date) -> str:
    first, last = _parse_day(rng.get("from")), _parse_day(rng.get("to"))
    if not first:
        return ""
    if last is None or last == first:
        p = _day(first, lang, today)
    elif lang == "de":
        p = f"vom {first.day}. {_MONTHS['de'][first.month - 1]} bis {last.day}. {_MONTHS['de'][last.month - 1]}"
    else:
        p = f"from {_MONTHS['en'][first.month - 1]} {first.day} to {_MONTHS['en'][last.month - 1]} {last.day}"
    return p[:1].upper() + p[1:]


def _list(r: dict, lang: str, voice: bool, today: date) -> str:
    events = r.get("events") or []
    rng = r.get("range") or {}
    remaining = int(r.get("remaining") or 0)
    multi_day = rng.get("from") != rng.get("to") or rng.get("next_only")

    if rng.get("next_only"):
        if not events:
            text = "Du hast keine anstehenden Termine." if lang == "de" else "You have no upcoming events."
        else:
            items = [f"{_title(e, lang)} {_when(e, lang, voice, today)}" for e in events]
            text = (f"Dein nächster Termin: {_join(items, lang)}." if lang == "de"
                    else f"Your next event: {_join(items, lang)}.")
        return text + _warnings(r, lang)

    phrase = _range_phrase(rng, lang, today)
    if not events:
        text = (f"{phrase} hast du keine Termine." if lang == "de" else f"{phrase} you have no events.")
        return text + _warnings(r, lang)

    total = int(r.get("total") or len(events))
    count = (f"{total} Termin{'e' if total != 1 else ''}" if lang == "de"
             else f"{total} event{'s' if total != 1 else ''}")
    lead = f"{phrase} hast du {count}" if lang == "de" else f"{phrase} you have {count}"

    def item(e: dict) -> str:
        when = _when(e, lang, voice, today, with_day=multi_day)
        title = e.get("title") or ""
        return f"{when} {title}".strip() if lang == "de" else f"{title} {when}".strip()

    if voice or len(events) <= 3:
        text = f"{lead}: {_join([item(e) for e in events], lang)}"
        if remaining:
            text += f" und {remaining} weitere" if lang == "de" else f" and {remaining} more"
        return text + "." + _warnings(r, lang)

    lines = [f"{lead}:"]
    for e in events:
        extra = [x for x in (e.get("location"), e.get("calendar")) if x]
        lines.append(f"- {item(e)}" + (f" ({', '.join(extra)})" if extra else ""))
    if remaining:
        lines.append(f"… und {remaining} weitere." if lang == "de" else f"… and {remaining} more.")
    return "\n".join(lines) + _warnings(r, lang)


def _warnings(r: dict, lang: str) -> str:
    warns = r.get("warnings") or []
    if not warns:
        return ""
    accounts = _join([w.get("account") or "?" for w in warns], lang)
    if lang == "de":
        return f" Hinweis: {accounts} war nicht abrufbar, die Liste ist eventuell unvollständig."
    return f" Note: {accounts} could not be read, the list may be incomplete."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def compose(result: dict, lang: str, channel: str, now: datetime | None = None) -> str | None:
    """Reply text for a calendar tool result, or None if the LLM must handle it."""
    if not isinstance(result, dict):
        return None
    lang = language(lang)
    voice = channel == "voice"
    today = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ).date()

    err = result.get("error")
    if err:
        if err in _LLM_HANDLED_ERRORS:
            return None
        return _ERRORS[lang].get(err, _ERRORS[lang]["calendar_unavailable"])

    status = result.get("status")
    if status == "created":
        return _created(result, lang, voice, today)
    if status == "updated":
        return _updated(result, lang, voice, today)
    if status == "deleted":
        return _deleted(result, lang)
    if status == "confirm_delete":
        return _confirm_delete(result, lang, voice, today)
    if status == "needs_scope":
        return _needs_scope(result, lang, voice, today)
    if status == "ambiguous":
        return _ambiguous(result, lang, voice, today)
    if status == "needs_calendar":
        return _needs_calendar(result, lang)
    if status == "confirm_past":
        return _confirm_past(result, lang, voice, today)
    if status == "not_found":
        return ("Ich habe keinen passenden Termin gefunden." if lang == "de"
                else "I couldn't find a matching event.")
    if status == "ok":
        return _list(result, lang, voice, today)
    return None


def is_terminal(result: dict) -> bool:
    """Finished outcome (no question pending) — the voice session may end."""
    return bool(result.get("error")) or result.get("status") in TERMINAL_STATUSES
