from datetime import date, datetime, time, timedelta

import pytest

from app import timeutil as tu

TZ = tu.zone("Europe/Berlin")
# Wednesday 2026-10-07, 09:30 local
NOW = datetime(2026, 10, 7, 9, 30, tzinfo=TZ)


# ---------------------------------------------------------------------------
# resolve_range
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kw,first,last", [
    ("today", date(2026, 10, 7), date(2026, 10, 7)),
    ("tomorrow", date(2026, 10, 8), date(2026, 10, 8)),
    ("day_after_tomorrow", date(2026, 10, 9), date(2026, 10, 9)),
    ("this_week", date(2026, 10, 7), date(2026, 10, 11)),
    ("next_week", date(2026, 10, 12), date(2026, 10, 18)),
])
def test_range_keywords(kw, first, last):
    r = tu.resolve_range(kw, TZ, NOW)
    assert (r.first_day, r.last_day) == (first, last)
    assert r.start == datetime.combine(first, time.min, tzinfo=TZ)
    assert r.end == datetime.combine(last + timedelta(days=1), time.min, tzinfo=TZ)


def test_range_this_week_on_sunday_is_one_day():
    sunday = datetime(2026, 10, 11, 12, 0, tzinfo=TZ)
    r = tu.resolve_range("this_week", TZ, sunday)
    assert r.first_day == r.last_day == date(2026, 10, 11)


def test_range_explicit_date_and_span():
    r = tu.resolve_range("date", TZ, NOW, "2026-12-24", "2026-12-26")
    assert (r.first_day, r.last_day) == (date(2026, 12, 24), date(2026, 12, 26))


def test_range_date_implied_when_date_given():
    r = tu.resolve_range(None, TZ, NOW, "2026-10-20")
    assert r.first_day == date(2026, 10, 20)


def test_range_next():
    r = tu.resolve_range("next", TZ, NOW)
    assert r.next_only and r.start == NOW


@pytest.mark.parametrize("args", [
    ("bogus", None, None),
    ("date", None, None),
    ("date", "2026/10/07", None),
    ("date", "2026-10-10", "2026-10-01"),
    ("date", "2026-01-01", "2026-12-31"),
])
def test_range_invalid(args):
    kw, d, d2 = args
    with pytest.raises(tu.InputError):
        tu.resolve_range(kw, TZ, NOW, d, d2)


# ---------------------------------------------------------------------------
# parse_event_times / describe_times
# ---------------------------------------------------------------------------
def test_parse_timed_event_utc_to_local():
    t = tu.parse_event_times({"start": {"dateTime": "2026-10-07T08:00:00Z"},
                              "end": {"dateTime": "2026-10-07T09:00:00Z"}}, TZ)
    assert not t.all_day and t.start.hour == 10 and t.end.hour == 11


def test_parse_multiday_all_day():
    t = tu.parse_event_times({"start": {"date": "2026-10-12"}, "end": {"date": "2026-10-17"}}, TZ)
    d = tu.describe_times(t)
    assert d["all_day"] and d["date"] == "2026-10-12" and d["end_date"] == "2026-10-16"
    assert d["weekday"] == "Monday" and d["end_weekday"] == "Friday"


def test_describe_single_day_all_day_has_no_end_date():
    t = tu.parse_event_times({"start": {"date": "2026-10-12"}, "end": {"date": "2026-10-13"}}, TZ)
    assert "end_date" not in tu.describe_times(t)


# ---------------------------------------------------------------------------
# build_times
# ---------------------------------------------------------------------------
def test_build_default_duration():
    s, e, t = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 8), time(10, 0))
    assert s == {"dateTime": "2026-10-08T10:00:00", "timeZone": "Europe/Berlin"}
    assert e["dateTime"] == "2026-10-08T11:00:00"


def test_build_all_day_without_time():
    s, e, t = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 8), None)
    assert s == {"date": "2026-10-08"} and e == {"date": "2026-10-09"} and t.all_day


def test_build_multi_day_all_day():
    s, e, _ = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 12), None, end_day=date(2026, 10, 16))
    assert e == {"date": "2026-10-17"}


def test_build_end_time_crossing_midnight():
    _, e, _ = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 8), time(22, 0), end_time=time(1, 0))
    assert e["dateTime"] == "2026-10-09T01:00:00"


def test_build_on_dst_switch_day_keeps_local_wall_clock():
    # 2026-10-25: CEST → CET. 10:00 local must stay 10:00 local (UTC+1).
    _, _, t = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 25), time(10, 0))
    assert t.start.utcoffset() == timedelta(hours=1)
    assert t.start.hour == 10


def test_is_in_past():
    _, _, past = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 7), time(8, 0))
    _, _, future = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 7), time(11, 0))
    _, _, today_all_day = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 7), None)
    assert tu.is_in_past(past, NOW)
    assert not tu.is_in_past(future, NOW)
    assert not tu.is_in_past(today_all_day, NOW)


# ---------------------------------------------------------------------------
# Recurrence
# ---------------------------------------------------------------------------
def _first(day=date(2026, 10, 7), at=time(10, 0)):
    return tu.build_times(TZ, "Europe/Berlin", day, at)[2]


def test_rrule_weekly_with_days_and_count():
    rule, idx = tu.build_rrule({"freq": "weekly", "weekdays": ["MO", "we"], "count": 10}, TZ, _first())
    assert rule == "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=10"
    assert idx == [0, 2]


def test_rrule_until_timed_is_utc_end_of_day():
    rule, _ = tu.build_rrule({"freq": "daily", "until": "2026-12-31"}, TZ, _first())
    assert rule == "RRULE:FREQ=DAILY;UNTIL=20261231T225959Z"


def test_rrule_until_all_day_is_date():
    first = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 7), None)[2]
    rule, _ = tu.build_rrule({"freq": "yearly", "until": "2030-10-07"}, TZ, first)
    assert rule == "RRULE:FREQ=YEARLY;UNTIL=20301007"


@pytest.mark.parametrize("rec", [
    {"freq": "weekly", "interval": 2},
    {"freq": "monthly", "byday": "2TU"},
    {"freq": "hourly"},
    {"freq": "monthly", "weekdays": ["TU"]},
])
def test_rrule_rejects_complex(rec):
    with pytest.raises(tu.UnsupportedRecurrence):
        tu.build_rrule(rec, TZ, _first())


def test_rrule_rejects_until_and_count():
    with pytest.raises(tu.InputError):
        tu.build_rrule({"freq": "daily", "until": "2026-12-31", "count": 3}, TZ, _first())


def test_align_to_weekday_moves_first_occurrence():
    # Requested on Wednesday "jeden Montag" → first event next Monday, same time.
    t = tu.align_to_weekdays(_first(), [0])
    assert t.start.date() == date(2026, 10, 12) and t.start.hour == 10
    assert t.end - t.start == timedelta(hours=1)


def test_align_noop_when_matching():
    first = _first()
    assert tu.align_to_weekdays(first, [2]) is first


# ---------------------------------------------------------------------------
# apply_time_change
# ---------------------------------------------------------------------------
def test_change_only_time_keeps_date_and_duration():
    cur = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 8), time(9, 0), duration_minutes=90)[2]
    new = tu.apply_time_change(cur, TZ, new_start_time=time(11, 0))
    assert new.start == datetime(2026, 10, 8, 11, 0, tzinfo=TZ)
    assert new.end - new.start == timedelta(minutes=90)


def test_change_only_date_keeps_time():
    cur = _first(date(2026, 10, 8), time(9, 0))
    new = tu.apply_time_change(cur, TZ, new_day=date(2026, 10, 9))
    assert new.start == datetime(2026, 10, 9, 9, 0, tzinfo=TZ)


def test_change_all_day_to_timed_requires_time():
    cur = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 8), None)[2]
    with pytest.raises(tu.InputError):
        tu.apply_time_change(cur, TZ, new_day=date(2026, 10, 9), all_day=False)
    new = tu.apply_time_change(cur, TZ, new_start_time=time(14, 0))
    assert not new.all_day and new.end - new.start == timedelta(hours=1)


def test_change_all_day_keeps_span_on_date_move():
    cur = tu.build_times(TZ, "Europe/Berlin", date(2026, 10, 12), None, end_day=date(2026, 10, 14))[2]
    new = tu.apply_time_change(cur, TZ, new_day=date(2026, 10, 19))
    assert new.all_day and (new.end - new.start).days == 3


@pytest.mark.parametrize("value,expected", [
    ("2026-10-06", date(2026, 10, 6)),
    ("06.10.2026", date(2026, 10, 6)),
    ("6.1.2027", date(2027, 1, 6)),
])
def test_parse_date_accepts_iso_and_german(value, expected):
    assert tu.parse_date(value) == expected


@pytest.mark.parametrize("value", ["31.02.2026", "06.10.", "2026/10/06", "morgen"])
def test_parse_date_rejects_invalid(value):
    with pytest.raises(tu.InputError):
        tu.parse_date(value)
