"""
Date/time helpers for the lists agent (PROJ-106). Pure — no I/O.

Due date and deadline are each stored as a timestamp plus a "has time" flag:
a date-only value is local midnight of the user's zone. Local wall-clock
values are converted with zoneinfo, so a time on the DST-switch day lands at
the correct local time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Europe/Berlin"

RANGE_KEYWORDS = ("today", "tomorrow", "day_after_tomorrow", "this_week", "next_week", "date",
                  "overdue", "all")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# The model sometimes answers in German notation despite the schema asking for
# ISO dates (seen live with PROJ-87) — accept DD.MM.YYYY as well.
_DATE_DE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")


class InputError(ValueError):
    """Invalid tool input. The message is shown to the LLM (German)."""


def zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def parse_date(value, field: str = "date") -> date | None:
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


def parse_time(value, field: str = "time") -> time | None:
    if value is None or str(value).strip() == "":
        return None
    m = _TIME_RE.match(str(value).strip())
    if not m:
        raise InputError(f"{field} muss im Format HH:MM angegeben werden")
    return time(int(m.group(1)), int(m.group(2)))


def local_midnight(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time.min, tzinfo=tz)


# ---------------------------------------------------------------------------
# Due / deadline values
# ---------------------------------------------------------------------------
@dataclass
class When:
    at: datetime          # tz-aware; local midnight when has_time is False
    has_time: bool

    def local_date(self, tz: ZoneInfo) -> date:
        return self.at.astimezone(tz).date()

    def is_past(self, now: datetime, tz: ZoneInfo) -> bool:
        if self.has_time:
            return self.at < now
        return self.local_date(tz) < now.astimezone(tz).date()


def build_when(d: date | None, t: time | None, tz: ZoneInfo, now: datetime) -> When | None:
    """Date and/or time → When. A time without a date means today, or tomorrow
    once that time has passed today (spec edge case)."""
    if d is None and t is None:
        return None
    if d is None:
        today = now.astimezone(tz).date()
        candidate = datetime.combine(today, t, tzinfo=tz)
        d = today if candidate > now else today + timedelta(days=1)
    if t is None:
        return When(local_midnight(d, tz), False)
    return When(datetime.combine(d, t, tzinfo=tz), True)


def describe_when(at: datetime | None, has_time: bool, tz: ZoneInfo) -> dict | None:
    """Result shape for templates: {"date": "YYYY-MM-DD", "time": "HH:MM"?}."""
    if at is None:
        return None
    local = at.astimezone(tz)
    out = {"date": local.date().isoformat()}
    if has_time:
        out["time"] = local.strftime("%H:%M")
    return out


# ---------------------------------------------------------------------------
# Query ranges
# ---------------------------------------------------------------------------
@dataclass
class QueryRange:
    keyword: str
    first_day: date | None   # inclusive; None = open
    last_day: date | None    # inclusive; None = open


def resolve_range(keyword: str | None, tz: ZoneInfo, now: datetime,
                  day=None, day_to=None, done: bool = False) -> QueryRange:
    """Range keyword (+ explicit dates) → local day window.

    Open items: "this_week" runs from today to Sunday (past days are covered
    by "overdue"). Done items look back instead: "this_week" is Monday..today,
    everything else the last 30 days (older done items are purged).
    """
    keyword = (keyword or "").strip().lower() or ("date" if day else "all")
    if keyword not in RANGE_KEYWORDS:
        raise InputError(f"range muss eines von {', '.join(RANGE_KEYWORDS)} sein")
    today = now.astimezone(tz).date()

    if done:
        if keyword == "today":
            return QueryRange(keyword, today, today)
        if keyword == "this_week":
            return QueryRange(keyword, today - timedelta(days=today.weekday()), today)
        if keyword == "date":
            first = parse_date(day, "date")
            if first is None:
                raise InputError("Für range=date muss date angegeben werden")
            return QueryRange(keyword, first, parse_date(day_to, "date_to") or first)
        return QueryRange("all", today - timedelta(days=30), today)

    if keyword in ("all", "overdue"):
        return QueryRange(keyword, None, None)
    if keyword == "today":
        first = last = today
    elif keyword == "tomorrow":
        first = last = today + timedelta(days=1)
    elif keyword == "day_after_tomorrow":
        first = last = today + timedelta(days=2)
    elif keyword == "this_week":
        first, last = today, today + timedelta(days=6 - today.weekday())
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
        if (last - first).days > 366:
            raise InputError("Der Abfragezeitraum darf höchstens ein Jahr umfassen")
    return QueryRange(keyword, first, last)
