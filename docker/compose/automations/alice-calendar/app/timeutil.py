"""
Date/time helpers for the calendar agent (PROJ-87).

Everything here is pure (no I/O) so it can be unit-tested exhaustively:
query-range resolution, Google event time parsing, start/end construction for
new or changed events, and the simple-recurrence → RRULE mapping.

Conventions:
  - All "local" values are in the user's IANA time zone (default Europe/Berlin).
  - Timed events are sent to Google as local wall-clock time plus the zone name,
    so Google resolves DST itself (an event on the DST-switch day lands at the
    correct local time).
  - All-day events use Google's exclusive end date (a one-day event on the 6th
    has end.date = the 7th).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Europe/Berlin"
DEFAULT_DURATION_MINUTES = 60
MAX_REMINDER_MINUTES = 40320  # Google limit: 4 weeks
MAX_RECURRENCE_COUNT = 730

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
RRULE_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

RANGE_KEYWORDS = ("today", "tomorrow", "day_after_tomorrow", "this_week", "next_week", "date", "next")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# The model sometimes answers in German notation despite the schema asking for
# ISO dates (seen live 2026-10-05) — accept DD.MM.YYYY as well.
_DATE_DE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")


class InputError(ValueError):
    """Invalid tool input. The message is shown to the LLM (German)."""


class UnsupportedRecurrence(InputError):
    """Recurrence rule beyond the simple MVP set."""


def zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def parse_date(value: str | None, field: str = "date") -> date | None:
    if value is None or str(value).strip() == "":
        return None
    value = str(value).strip()
    de = _DATE_DE_RE.match(value)
    if not de and not _DATE_RE.match(value):
        raise InputError(f"{field} muss im Format YYYY-MM-DD angegeben werden")
    try:
        if de:
            return date(int(de.group(3)), int(de.group(2)), int(de.group(1)))
        return date.fromisoformat(value)
    except ValueError:
        raise InputError(f"{field} ist kein gültiges Datum: {value}")


def parse_time(value: str | None, field: str = "start_time") -> time | None:
    if value is None or str(value).strip() == "":
        return None
    m = _TIME_RE.match(str(value).strip())
    if not m:
        raise InputError(f"{field} muss im Format HH:MM angegeben werden")
    return time(int(m.group(1)), int(m.group(2)))


def local_midnight(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time.min, tzinfo=tz)


# ---------------------------------------------------------------------------
# Query ranges
# ---------------------------------------------------------------------------
@dataclass
class QueryRange:
    start: datetime          # inclusive, tz-aware
    end: datetime            # exclusive, tz-aware
    first_day: date
    last_day: date           # inclusive
    next_only: bool = False  # "nächster Termin"


def resolve_range(
    keyword: str | None,
    tz: ZoneInfo,
    now: datetime,
    day: str | None = None,
    day_to: str | None = None,
) -> QueryRange:
    """Turn a range keyword (+ optional explicit dates) into a local window.

    "this_week" runs from today to the end of Sunday (past days of the week
    are not interesting); "next_week" is next Monday..Sunday.
    """
    keyword = (keyword or "").strip().lower() or ("date" if day else "today")
    if keyword not in RANGE_KEYWORDS:
        raise InputError(f"range muss eines von {', '.join(RANGE_KEYWORDS)} sein")

    today = now.astimezone(tz).date()

    if keyword == "next":
        start = now.astimezone(tz)
        end = start + timedelta(days=365)
        return QueryRange(start, end, today, end.date(), next_only=True)

    if keyword == "today":
        first = last = today
    elif keyword == "tomorrow":
        first = last = today + timedelta(days=1)
    elif keyword == "day_after_tomorrow":
        first = last = today + timedelta(days=2)
    elif keyword == "this_week":
        first = today
        last = today + timedelta(days=6 - today.weekday())
    elif keyword == "next_week":
        first = today + timedelta(days=7 - today.weekday())
        last = first + timedelta(days=6)
    else:  # date
        first = parse_date(day, "date")
        if first is None:
            raise InputError("Für range=date muss date angegeben werden")
        last = parse_date(day_to, "date_to") or first
        if last < first:
            raise InputError("date_to darf nicht vor date liegen")
        if (last - first).days > 62:
            raise InputError("Der Abfragezeitraum darf höchstens 62 Tage umfassen")

    return QueryRange(
        local_midnight(first, tz),
        local_midnight(last + timedelta(days=1), tz),
        first,
        last,
    )


# ---------------------------------------------------------------------------
# Google event time parsing
# ---------------------------------------------------------------------------
@dataclass
class EventTimes:
    start: datetime   # tz-aware (all-day: local midnight)
    end: datetime     # tz-aware, exclusive
    all_day: bool


def parse_event_times(event: dict, tz: ZoneInfo) -> EventTimes:
    s = event.get("start") or {}
    e = event.get("end") or {}
    if "date" in s and "dateTime" not in s:
        start_d = date.fromisoformat(s["date"])
        end_d = date.fromisoformat(e["date"]) if e.get("date") else start_d + timedelta(days=1)
        return EventTimes(local_midnight(start_d, tz), local_midnight(end_d, tz), True)
    start = datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00")).astimezone(tz)
    end_raw = e.get("dateTime")
    end = datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone(tz) if end_raw else start
    return EventTimes(start, end, False)


def describe_times(t: EventTimes) -> dict:
    """Structured, language-neutral time description for the LLM."""
    out: dict = {
        "date": t.start.date().isoformat(),
        "weekday": WEEKDAY_NAMES[t.start.weekday()],
        "all_day": t.all_day,
    }
    if t.all_day:
        last_day = (t.end - timedelta(days=1)).date()
        if last_day > t.start.date():
            out["end_date"] = last_day.isoformat()
            out["end_weekday"] = WEEKDAY_NAMES[last_day.weekday()]
    else:
        out["start_time"] = t.start.strftime("%H:%M")
        out["end_time"] = t.end.strftime("%H:%M")
        if t.end.date() != t.start.date():
            out["end_date"] = t.end.date().isoformat()
    return out


# ---------------------------------------------------------------------------
# Building start/end for new events
# ---------------------------------------------------------------------------
def _google_time(dt: datetime, tz_name: str) -> dict:
    return {"dateTime": dt.replace(tzinfo=None).isoformat(timespec="seconds"), "timeZone": tz_name}


def build_times(
    tz: ZoneInfo,
    tz_name: str,
    day: date,
    start_time: time | None,
    end_time: time | None = None,
    duration_minutes: int | None = None,
    end_day: date | None = None,
) -> tuple[dict, dict, EventTimes]:
    """Return (google_start, google_end, EventTimes) for an event.

    Without start_time the event is all-day (optionally spanning to end_day).
    """
    if start_time is None:
        last = end_day or day
        if last < day:
            raise InputError("end_date darf nicht vor date liegen")
        times = EventTimes(local_midnight(day, tz), local_midnight(last + timedelta(days=1), tz), True)
        return (
            {"date": day.isoformat()},
            {"date": (last + timedelta(days=1)).isoformat()},
            times,
        )

    start = datetime.combine(day, start_time, tzinfo=tz)
    if end_time is not None:
        end = datetime.combine(end_day or day, end_time, tzinfo=tz)
        if end <= start:
            if end_day is None:
                end += timedelta(days=1)  # "22 bis 1 Uhr" crosses midnight
            else:
                raise InputError("Das Ende muss nach dem Beginn liegen")
    else:
        minutes = DEFAULT_DURATION_MINUTES if duration_minutes is None else int(duration_minutes)
        if minutes <= 0 or minutes > 14 * 24 * 60:
            raise InputError("duration_minutes muss zwischen 1 und 20160 liegen")
        end = start + timedelta(minutes=minutes)
    return _google_time(start, tz_name), _google_time(end, tz_name), EventTimes(start, end, False)


def times_to_google(t: EventTimes, tz_name: str) -> tuple[dict, dict]:
    if t.all_day:
        return {"date": t.start.date().isoformat()}, {"date": t.end.date().isoformat()}
    return _google_time(t.start, tz_name), _google_time(t.end, tz_name)


def is_in_past(t: EventTimes, now: datetime) -> bool:
    if t.all_day:
        return t.start.date() < now.astimezone(t.start.tzinfo).date()
    return t.start < now


# ---------------------------------------------------------------------------
# Simple recurrence
# ---------------------------------------------------------------------------
_FREQS = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY"}


def build_rrule(
    recurrence: dict,
    tz: ZoneInfo,
    first_start: EventTimes,
) -> tuple[str, list[int]]:
    """Map the simple recurrence object to an RRULE line.

    Supported: freq daily|weekly|monthly|yearly, weekdays (weekly only),
    until (date) or count. Anything else (interval, nth weekday of month, ...)
    is rejected — the spec sends the user to Google for complex rules.
    Returns (rrule, weekday_indices).
    """
    if not isinstance(recurrence, dict):
        raise InputError("recurrence muss ein Objekt sein")
    unknown = set(recurrence) - {"freq", "weekdays", "until", "count"}
    if unknown:
        raise UnsupportedRecurrence(
            "Nur einfache Wiederholungen (täglich, wöchentlich mit Wochentagen, monatlich, "
            "jährlich, optional mit Ende) werden unterstützt"
        )
    freq = str(recurrence.get("freq") or "").strip().lower()
    if freq not in _FREQS:
        raise UnsupportedRecurrence("freq muss daily, weekly, monthly oder yearly sein")

    parts = [f"FREQ={_FREQS[freq]}"]

    weekday_idx: list[int] = []
    weekdays = recurrence.get("weekdays") or []
    if weekdays:
        if freq != "weekly":
            raise UnsupportedRecurrence("Wochentage sind nur bei wöchentlicher Wiederholung möglich")
        for wd in weekdays:
            code = str(wd).strip().upper()[:2]
            if code not in RRULE_DAYS:
                raise InputError(f"Unbekannter Wochentag: {wd} (erwartet MO..SU)")
            idx = RRULE_DAYS.index(code)
            if idx not in weekday_idx:
                weekday_idx.append(idx)
        weekday_idx.sort()
        parts.append("BYDAY=" + ",".join(RRULE_DAYS[i] for i in weekday_idx))

    until = parse_date(recurrence.get("until"), "recurrence.until")
    count = recurrence.get("count")
    if until and count:
        raise InputError("recurrence: entweder until oder count angeben, nicht beides")
    if count is not None and str(count).strip() != "":
        try:
            n = int(count)
        except (TypeError, ValueError):
            raise InputError("recurrence.count muss eine Zahl sein")
        if n < 1 or n > MAX_RECURRENCE_COUNT:
            raise InputError(f"recurrence.count muss zwischen 1 und {MAX_RECURRENCE_COUNT} liegen")
        parts.append(f"COUNT={n}")
    if until:
        if until < first_start.start.date():
            raise InputError("recurrence.until liegt vor dem ersten Termin")
        if first_start.all_day:
            parts.append(f"UNTIL={until.strftime('%Y%m%d')}")
        else:
            # Inclusive end of that local day, expressed in UTC (RFC 5545).
            end_local = datetime.combine(until, time(23, 59, 59), tzinfo=tz)
            parts.append("UNTIL=" + end_local.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ"))

    return "RRULE:" + ";".join(parts), weekday_idx



def align_to_weekdays(t: EventTimes, weekday_idx: list[int]) -> EventTimes:
    """Move the first occurrence forward to the first listed weekday.

    Google treats DTSTART as an occurrence even if it does not match BYDAY, so
    "jeden Montag" requested on a Wednesday would otherwise create a stray
    Wednesday event.
    """
    if not weekday_idx or t.start.weekday() in weekday_idx:
        return t
    for shift in range(1, 7):
        if (t.start.weekday() + shift) % 7 in weekday_idx:
            delta = timedelta(days=shift)
            return _shift_local(t, delta)
    return t


def _shift_local(t: EventTimes, delta: timedelta) -> EventTimes:
    """Shift by whole days keeping the local wall-clock time (DST-safe)."""
    tz = t.start.tzinfo
    start = datetime.combine(t.start.date() + delta, t.start.timetz().replace(tzinfo=None), tzinfo=tz)
    duration = t.end - t.start
    if t.all_day:
        days = round(duration.total_seconds() / 86400)
        end = local_midnight(start.date() + timedelta(days=days), tz)
    else:
        end = start + duration
    return EventTimes(start, end, t.all_day)


def describe_rrule(rrule: str) -> str:
    """Compact human hint of a stored RRULE (the LLM phrases it)."""
    return rrule.replace("RRULE:", "")


# ---------------------------------------------------------------------------
# Changing an existing event's time
# ---------------------------------------------------------------------------
def apply_time_change(
    current: EventTimes,
    tz: ZoneInfo,
    new_day: date | None = None,
    new_start_time: time | None = None,
    new_end_time: time | None = None,
    duration_minutes: int | None = None,
    all_day: bool | None = None,
) -> EventTimes:
    """Compute the new start/end of an event from partial changes.

    Unchanged parts are kept: moving "auf 11 Uhr" keeps date and duration,
    moving "auf Freitag" keeps time and duration.
    """
    day = new_day or current.start.date()

    to_all_day = all_day is True or (current.all_day and all_day is None and new_start_time is None)
    if to_all_day:
        span_days = max(1, round((current.end - current.start).total_seconds() / 86400)) if current.all_day else 1
        return EventTimes(local_midnight(day, tz), local_midnight(day + timedelta(days=span_days), tz), True)

    if current.all_day:
        # all-day → timed needs a start time
        if new_start_time is None:
            raise InputError("Für einen Termin mit Uhrzeit wird start_time benötigt")
        duration = timedelta(minutes=duration_minutes or DEFAULT_DURATION_MINUTES)
    else:
        duration = current.end - current.start
        if duration_minutes is not None:
            if int(duration_minutes) <= 0 or int(duration_minutes) > 14 * 24 * 60:
                raise InputError("duration_minutes muss zwischen 1 und 20160 liegen")
            duration = timedelta(minutes=int(duration_minutes))

    start_t = new_start_time or current.start.timetz().replace(tzinfo=None)
    start = datetime.combine(day, start_t, tzinfo=tz)
    if new_end_time is not None:
        end = datetime.combine(day, new_end_time, tzinfo=tz)
        if end <= start:
            end += timedelta(days=1)
    else:
        end = start + duration
    return EventTimes(start, end, False)
