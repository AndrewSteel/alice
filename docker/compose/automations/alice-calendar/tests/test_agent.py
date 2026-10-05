from datetime import datetime

import pytest

from app import agent, google
from app import timeutil as tu
from tests.conftest import CONN_A, CONN_B, TZ


def ev_time(day, hh, mm=0):
    return datetime(*day, hh, mm, tzinfo=TZ).isoformat()


# ---------------------------------------------------------------------------
# list_events
# ---------------------------------------------------------------------------
async def test_list_merges_active_calendars_chronologically(basic, make_ctx):
    basic.add_event(CONN_A, "family", "Elternabend", ev_time((2026, 10, 8), 19), ev_time((2026, 10, 8), 20),
                    location="Schule")
    basic.add_event(CONN_A, "primary-a", "Zahnarzt", ev_time((2026, 10, 8), 10), ev_time((2026, 10, 8), 11))
    basic.add_event(CONN_A, "holidays", "Feiertag", "2026-10-08", "2026-10-09", all_day=True)
    res = await agent.list_events(make_ctx(), {"range": "tomorrow"})
    assert res["status"] == "ok" and res["total"] == 3
    titles = [e["title"] for e in res["events"]]
    assert titles == ["Feiertag", "Zahnarzt", "Elternabend"]   # all-day first, then by time
    assert res["events"][1]["start_time"] == "10:00"
    assert res["events"][2]["location"] == "Schule"
    assert res["events"][2]["calendar"] == "Familie"           # >1 active calendar → named


async def test_list_hides_calendar_name_with_single_calendar(fg, fdb, make_ctx):
    fg.add_connection(CONN_A, "me@gmail.com")
    fg.add_calendar(CONN_A, "c1", "Privat")
    fdb.select(CONN_A, "c1", default=True)
    fg.add_event(CONN_A, "c1", "Sport", ev_time((2026, 10, 7), 18), ev_time((2026, 10, 7), 19))
    res = await agent.list_events(make_ctx(), {"range": "today"})
    assert "calendar" not in res["events"][0]


async def test_list_voice_limit_five_with_remaining(basic, make_ctx):
    for h in range(10, 18):
        basic.add_event(CONN_A, "primary-a", f"T{h}", ev_time((2026, 10, 7), h), ev_time((2026, 10, 7), h, 30))
    voice = await agent.list_events(make_ctx(channel="voice"), {"range": "today"})
    assert len(voice["events"]) == 5 and voice["remaining"] == 3 and "3 weitere" in voice["instruction"]
    chat = await agent.list_events(make_ctx(), {"range": "today"})
    assert len(chat["events"]) == 8 and chat["remaining"] == 0


async def test_list_chat_truncates_at_50(basic, make_ctx):
    for i in range(55):
        basic.add_event(CONN_A, "primary-a", f"E{i}", ev_time((2026, 10, 12), 8 + i // 6, (i % 6) * 10),
                        ev_time((2026, 10, 12), 8 + i // 6, (i % 6) * 10 + 5))
    res = await agent.list_events(make_ctx(), {"range": "next_week"})
    assert len(res["events"]) == 50 and res["remaining"] == 5 and "gekürzt" in res["instruction"]


async def test_list_empty_says_no_events(basic, make_ctx):
    res = await agent.list_events(make_ctx(), {"range": "today"})
    assert res["total"] == 0 and "keine Termine" in res["instruction"]


async def test_list_multiday_all_day_appears_on_middle_day(basic, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Urlaub", "2026-10-12", "2026-10-17", all_day=True)
    res = await agent.list_events(make_ctx(), {"range": "date", "date": "2026-10-14"})
    assert [e["title"] for e in res["events"]] == ["Urlaub"]
    assert res["events"][0]["end_date"] == "2026-10-16"


async def test_list_next_event(basic, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Vorbei", ev_time((2026, 10, 7), 8), ev_time((2026, 10, 7), 9))
    basic.add_event(CONN_A, "family", "Später", ev_time((2026, 10, 9), 8), ev_time((2026, 10, 9), 9))
    basic.add_event(CONN_A, "primary-a", "Bald", ev_time((2026, 10, 7), 14), ev_time((2026, 10, 7), 15))
    res = await agent.list_events(make_ctx(), {"range": "next"})
    assert [e["title"] for e in res["events"]] == ["Bald"]


async def test_list_partial_failure_reports_warning(basic, fdb, make_ctx):
    basic.add_connection(CONN_B, "work@firma.de")
    basic.add_calendar(CONN_B, "work", "Arbeit")
    fdb.select(CONN_B, "work")
    basic.token_errors[CONN_B] = google.ReauthRequired(CONN_B)
    basic.add_event(CONN_A, "primary-a", "Zahnarzt", ev_time((2026, 10, 7), 10), ev_time((2026, 10, 7), 11))
    res = await agent.list_events(make_ctx(), {"range": "today"})
    assert res["total"] == 1
    assert res["warnings"] == [{"account": "work@firma.de", "problem": "reauth_required"}]


async def test_list_all_failing_never_reports_empty(fg, fdb, make_ctx):
    fg.add_connection(CONN_A, "me@gmail.com")
    fg.add_calendar(CONN_A, "c1", "Privat")
    fdb.select(CONN_A, "c1")
    fg.calendar_errors[(CONN_A, "c1")] = google.Unavailable("x")
    res = await agent.list_events(make_ctx(), {"range": "today"})
    assert res["error"] == "calendar_unavailable"


async def test_list_reauth_only_account(fg, fdb, make_ctx):
    fg.add_connection(CONN_A, "me@gmail.com", status="error")
    fdb.select(CONN_A, "c1")
    res = await agent.list_events(make_ctx(), {"range": "today"})
    assert res["error"] == "reauth_required" and "Einstellungen" in res["message"]


async def test_list_no_active_calendar(fg, fdb, make_ctx):
    fg.add_connection(CONN_A, "me@gmail.com")
    res = await agent.list_events(make_ctx(), {"range": "today"})
    assert res["error"] == "no_active_calendar"


async def test_list_skips_vanished_calendar(basic, fdb, make_ctx):
    fdb.select(CONN_A, "deleted-in-google")
    basic.add_event(CONN_A, "primary-a", "Zahnarzt", ev_time((2026, 10, 7), 10), ev_time((2026, 10, 7), 11))
    res = await agent.list_events(make_ctx(), {"range": "today"})
    assert res["total"] == 1 and "warnings" not in res


async def test_list_ignores_connection_without_scope(fg, fdb, make_ctx):
    fg.add_connection(CONN_A, "me@gmail.com", scopes=["openid", "email", "https://www.googleapis.com/auth/tasks"])
    fdb.select(CONN_A, "c1")
    res = await agent.list_events(make_ctx(), {"range": "today"})
    assert res["error"] == "no_active_calendar"
    assert ("token", CONN_A) not in fg.calls


class _Resp:
    def __init__(self, code):
        self.status_code = code

    def json(self):
        return {"access_token": "t"}


class _TokenClient:
    def __init__(self, codes):
        self.codes = list(codes)
        self.calls = 0

    async def post(self, *a, **k):
        self.calls += 1
        return _Resp(self.codes.pop(0))


async def _noop_sleep(*_):
    return None


async def test_token_503_retried_once(monkeypatch):
    monkeypatch.setattr(google.asyncio, "sleep", _noop_sleep)
    client = _TokenClient([503, 200])
    assert await google.get_access_token(client, "jwt", CONN_A) == "t"
    assert client.calls == 2


async def test_token_second_503_is_unavailable(monkeypatch):
    monkeypatch.setattr(google.asyncio, "sleep", _noop_sleep)
    client = _TokenClient([503, 503])
    with pytest.raises(google.Unavailable):
        await google.get_access_token(client, "jwt", CONN_A)
    assert client.calls == 2


async def test_token_409_is_reauth_without_retry():
    client = _TokenClient([409])
    with pytest.raises(google.ReauthRequired):
        await google.get_access_token(client, "jwt", CONN_A)
    assert client.calls == 1


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------
async def test_create_uses_default_calendar_and_confirms(basic, make_ctx):
    res = await agent.create_event(make_ctx(), {"title": "Zahnarzt", "date": "2026-10-08",
                                                "start_time": "10:00", "location": "Praxis",
                                                "reminder_minutes": 30})
    assert res["status"] == "created"
    ev = res["event"]
    assert ev["calendar"] == "Privat" and ev["start_time"] == "10:00" and ev["end_time"] == "11:00"
    assert ev["reminder_minutes"] == [30]
    body = basic.calls[-1][3]
    assert body["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]}
    assert body["start"]["timeZone"] == "Europe/Berlin"


async def test_create_without_time_is_all_day(basic, make_ctx):
    res = await agent.create_event(make_ctx(), {"title": "Geburtstag", "date": "2026-10-20"})
    assert res["event"]["all_day"] is True
    assert basic.calls[-1][3]["end"] == {"date": "2026-10-21"}


async def test_create_named_calendar(basic, make_ctx):
    res = await agent.create_event(make_ctx(), {"title": "Elternabend", "date": "2026-10-08",
                                                "start_time": "19:00", "calendar": "Familienkalender"})
    assert res["event"]["calendar"] == "Familie"


async def test_create_unknown_calendar_asks(basic, make_ctx):
    res = await agent.create_event(make_ctx(), {"title": "X", "date": "2026-10-08", "calendar": "Arbeit"})
    assert res["status"] == "needs_calendar" and set(res["options"]) == {"Privat", "Familie"}


async def test_create_without_default_asks(basic, fdb, make_ctx):
    for r in fdb.rows:
        r["is_default"] = False
    res = await agent.create_event(make_ctx(), {"title": "X", "date": "2026-10-08"})
    assert res["status"] == "needs_calendar" and res["reason"] == "no_default"
    assert "Feiertage in Deutschland" not in res["options"]


async def test_create_in_read_only_calendar_rejected(basic, make_ctx):
    res = await agent.create_event(make_ctx(), {"title": "X", "date": "2026-10-08", "calendar": "Feiertage"})
    assert res["error"] == "read_only_calendar"
    assert not [c for c in basic.calls if c[0] == "insert"]


async def test_create_in_past_asks_first(basic, make_ctx):
    res = await agent.create_event(make_ctx(), {"title": "X", "date": "2026-10-07", "start_time": "08:00"})
    assert res["status"] == "confirm_past"
    assert not [c for c in basic.calls if c[0] == "insert"]
    ok = await agent.create_event(make_ctx(), {"title": "X", "date": "2026-10-07", "start_time": "08:00",
                                               "confirm_past": True})
    assert ok["status"] == "created"


async def test_create_weekly_recurrence_aligned(basic, make_ctx):
    res = await agent.create_event(make_ctx(), {"title": "Yoga", "date": "2026-10-07", "start_time": "18:00",
                                                "recurrence": {"freq": "weekly", "weekdays": ["MO"],
                                                               "until": "2026-12-31"}})
    body = basic.calls[-1][3]
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261231T225959Z"]
    assert body["start"]["dateTime"] == "2026-10-12T18:00:00"
    assert res["event"]["date"] == "2026-10-12"


async def test_create_complex_recurrence_raises(basic, make_ctx):
    with pytest.raises(tu.UnsupportedRecurrence):
        await agent.create_event(make_ctx(), {"title": "X", "date": "2026-10-08",
                                              "recurrence": {"freq": "monthly", "interval": 2}})


async def test_create_google_failure_is_no_success(basic, monkeypatch, make_ctx):
    async def boom(*a, **k):
        raise google.Unavailable("down")
    monkeypatch.setattr(google, "insert_event", boom)
    res = await agent.create_event(make_ctx(), {"title": "X", "date": "2026-10-08"})
    assert res["error"] == "calendar_unavailable" and "status" not in res


# ---------------------------------------------------------------------------
# update_event
# ---------------------------------------------------------------------------
async def test_update_moves_time_keeps_duration(basic, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Zahnarzttermin", ev_time((2026, 10, 8), 9), ev_time((2026, 10, 8), 9, 45))
    res = await agent.update_event(make_ctx(), {"title_query": "Zahnarzt", "new_start_time": "11:00"})
    assert res["status"] == "updated"
    assert res["event"]["start_time"] == "11:00" and res["event"]["end_time"] == "11:45"


async def test_update_ambiguous_lists_candidates(basic, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Meeting A", ev_time((2026, 10, 8), 9), ev_time((2026, 10, 8), 10))
    basic.add_event(CONN_A, "family", "Meeting B", ev_time((2026, 10, 8), 11), ev_time((2026, 10, 8), 12))
    res = await agent.update_event(make_ctx(), {"date": "2026-10-08", "new_start_time": "15:00"})
    assert res["status"] == "ambiguous" and len(res["candidates"]) == 2
    assert not [c for c in basic.calls if c[0] == "patch"]
    ref = res["candidates"][1]["event_ref"]
    done = await agent.update_event(make_ctx(), {"event_ref": ref, "new_start_time": "15:00"})
    assert done["status"] == "updated" and done["event"]["title"] == "Meeting B"


async def test_update_not_found(basic, make_ctx):
    res = await agent.update_event(make_ctx(), {"title_query": "Friseur", "new_start_time": "11:00"})
    assert res["status"] == "not_found"


async def test_update_series_asks_scope_then_patches_master(basic, make_ctx):
    # Master starts 2026-10-05 (outside the search window); listing shows instances.
    basic.add_event(CONN_A, "primary-a", "Yoga", ev_time((2026, 10, 5), 18), ev_time((2026, 10, 5), 19),
                    id="yoga", recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO"])
    for d in (12, 19):
        basic.add_event(CONN_A, "primary-a", "Yoga", ev_time((2026, 10, d), 18), ev_time((2026, 10, d), 19),
                        id=f"yoga_202610{d}", recurringEventId="yoga")

    ask = await agent.update_event(make_ctx(), {"title_query": "Yoga", "new_start_time": "19:00"})
    assert ask["status"] == "needs_scope"
    assert ask["event"]["date"] == "2026-10-12"      # one series collapsed to next occurrence
    res = await agent.update_event(make_ctx(), {"event_ref": ask["event"]["event_ref"], "scope": "series",
                                                "new_start_time": "19:00"})
    assert res["status"] == "updated" and res["scope"] == "series"
    patch = [c for c in basic.calls if c[0] == "patch"][-1]
    assert patch[2] == "yoga" and patch[3]["start"]["dateTime"] == "2026-10-05T19:00:00"
    assert patch[3]["end"]["dateTime"] == "2026-10-05T20:00:00"


async def test_update_single_occurrence_patches_instance(basic, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Yoga", ev_time((2026, 10, 5), 18), ev_time((2026, 10, 5), 19),
                    id="yoga", recurrence=["RRULE:FREQ=WEEKLY"])
    basic.add_event(CONN_A, "primary-a", "Yoga", ev_time((2026, 10, 12), 18), ev_time((2026, 10, 12), 19),
                    id="yoga_1012", recurringEventId="yoga")
    res = await agent.update_event(make_ctx(), {"title_query": "Yoga", "date": "2026-10-12", "scope": "single",
                                                "new_start_time": "20:00"})
    assert res["scope"] == "single"
    assert [c for c in basic.calls if c[0] == "patch"][-1][2] == "yoga_1012"


async def test_update_series_date_change_rejected(basic, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Yoga", ev_time((2026, 10, 5), 18), ev_time((2026, 10, 5), 19),
                    id="yoga", recurrence=["RRULE:FREQ=WEEKLY"])
    inst = basic.add_event(CONN_A, "primary-a", "Yoga", ev_time((2026, 10, 12), 18),
                           ev_time((2026, 10, 12), 19), id="yoga_1", recurringEventId="yoga")
    ref = agent.encode_ref(agent.Cal(CONN_A, "", "primary-a", "", None, False, False, False), inst["id"])
    with pytest.raises(tu.InputError):
        await agent.update_event(make_ctx(), {"event_ref": ref, "scope": "series", "new_date": "2026-10-13"})


async def test_update_calendar_change_same_account_moves(basic, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Elternabend", ev_time((2026, 10, 8), 19), ev_time((2026, 10, 8), 20))
    res = await agent.update_event(make_ctx(), {"title_query": "Elternabend", "new_calendar": "Familie"})
    assert res["event"]["calendar"] == "Familie"
    assert [c for c in basic.calls if c[0] == "move"]


async def test_update_read_only_rejected(basic, make_ctx):
    basic.add_event(CONN_A, "holidays", "Tag der Einheit", "2026-10-08", "2026-10-09", all_day=True)
    res = await agent.update_event(make_ctx(), {"title_query": "Einheit", "new_title": "X"})
    assert res["error"] == "read_only_calendar"


async def test_update_requires_change(basic, make_ctx):
    with pytest.raises(tu.InputError):
        await agent.update_event(make_ctx(), {"title_query": "Zahnarzt"})


async def test_event_ref_of_foreign_calendar_not_found(basic, make_ctx):
    foreign = agent.Cal("cccccccc-0000-0000-0000-000000000003", "", "other", "", None, False, False, False)
    res = await agent.update_event(make_ctx(), {"event_ref": agent.encode_ref(foreign, "x"), "new_title": "Y"})
    assert res["status"] == "not_found"


# ---------------------------------------------------------------------------
# Delete (two-stage, turn-bound)
# ---------------------------------------------------------------------------
async def test_delete_requires_next_turn_confirmation(basic, fredis, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Zahnarzt", ev_time((2026, 10, 8), 10), ev_time((2026, 10, 8), 11))
    prep = await agent.prepare_delete(make_ctx(turn=3), {"title_query": "Zahnarzt"})
    assert prep["status"] == "confirm_delete" and prep["event"]["calendar"] == "Privat"
    assert not [c for c in basic.calls if c[0] == "delete"]

    same = await agent.confirm_delete(make_ctx(turn=3), {"ticket": prep["ticket"]})
    assert same["error"] == "ticket_same_turn"
    assert not [c for c in basic.calls if c[0] == "delete"]

    ok = await agent.confirm_delete(make_ctx(turn=4), {"ticket": prep["ticket"]})
    assert ok["status"] == "deleted"
    assert [c for c in basic.calls if c[0] == "delete"]

    again = await agent.confirm_delete(make_ctx(turn=4), {"ticket": prep["ticket"]})
    assert again["error"] == "ticket_unknown"


async def test_delete_ticket_expires_after_unrelated_turn(basic, fredis, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Zahnarzt", ev_time((2026, 10, 8), 10), ev_time((2026, 10, 8), 11))
    prep = await agent.prepare_delete(make_ctx(turn=3), {"title_query": "Zahnarzt"})
    res = await agent.confirm_delete(make_ctx(turn=5), {"ticket": prep["ticket"]})
    assert res["error"] == "ticket_expired"
    assert not [c for c in basic.calls if c[0] == "delete"]


async def test_delete_ticket_bound_to_session_and_user(basic, fredis, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Zahnarzt", ev_time((2026, 10, 8), 10), ev_time((2026, 10, 8), 11))
    prep = await agent.prepare_delete(make_ctx(turn=3), {"title_query": "Zahnarzt"})
    other_session = await agent.confirm_delete(make_ctx(turn=4, session="s2"), {"ticket": prep["ticket"]})
    other_user = await agent.confirm_delete(make_ctx(turn=4, user="22222222-2222-2222-2222-222222222222"),
                                            {"ticket": prep["ticket"]})
    assert other_session["error"] == other_user["error"] == "ticket_wrong_owner"
    # still redeemable by the rightful owner afterwards
    assert (await agent.confirm_delete(make_ctx(turn=4), {"ticket": prep["ticket"]}))["status"] == "deleted"


async def test_delete_detects_parallel_change(basic, fredis, make_ctx):
    ev = basic.add_event(CONN_A, "primary-a", "Zahnarzt", ev_time((2026, 10, 8), 10), ev_time((2026, 10, 8), 11))
    prep = await agent.prepare_delete(make_ctx(turn=1), {"title_query": "Zahnarzt"})
    ev["etag"] = '"changed"'
    res = await agent.confirm_delete(make_ctx(turn=2), {"ticket": prep["ticket"]})
    assert res["error"] == "event_changed"
    assert not [c for c in basic.calls if c[0] == "delete"]


async def test_delete_detects_already_deleted(basic, fredis, make_ctx):
    ev = basic.add_event(CONN_A, "primary-a", "Zahnarzt", ev_time((2026, 10, 8), 10), ev_time((2026, 10, 8), 11))
    prep = await agent.prepare_delete(make_ctx(turn=1), {"title_query": "Zahnarzt"})
    basic.events[(CONN_A, "primary-a")].remove(ev)
    res = await agent.confirm_delete(make_ctx(turn=2), {"ticket": prep["ticket"]})
    assert res["error"] == "event_gone"


async def test_delete_series_asks_scope_and_targets_master(basic, fredis, make_ctx):
    basic.add_event(CONN_A, "primary-a", "Yoga", ev_time((2026, 10, 5), 18), ev_time((2026, 10, 5), 19),
                    id="yoga", recurrence=["RRULE:FREQ=WEEKLY"])
    inst = basic.add_event(CONN_A, "primary-a", "Yoga", ev_time((2026, 10, 12), 18),
                           ev_time((2026, 10, 12), 19), id="yoga_1012", recurringEventId="yoga")
    ask = await agent.prepare_delete(make_ctx(turn=1), {"date": "2026-10-12", "title_query": "Yoga"})
    assert ask["status"] == "needs_scope"
    prep = await agent.prepare_delete(make_ctx(turn=2), {"event_ref": ask["event"]["event_ref"],
                                                         "scope": "series"})
    assert prep["status"] == "confirm_delete" and prep["scope"] == "series"
    ok = await agent.confirm_delete(make_ctx(turn=3), {"ticket": prep["ticket"]})
    assert ok["status"] == "deleted"
    assert ("delete", "primary-a", "yoga") in basic.calls
    assert inst in basic.events[(CONN_A, "primary-a")]   # fake only removes the master


async def test_delete_read_only_rejected(basic, fredis, make_ctx):
    basic.add_event(CONN_A, "holidays", "Tag der Einheit", "2026-10-08", "2026-10-09", all_day=True)
    res = await agent.prepare_delete(make_ctx(), {"title_query": "Einheit"})
    assert res["error"] == "read_only_calendar"


async def test_confirm_rejected_when_calendar_deactivated(basic, fdb, fredis, make_ctx):
    basic.add_event(CONN_A, "family", "Elternabend", ev_time((2026, 10, 8), 19), ev_time((2026, 10, 8), 20))
    prep = await agent.prepare_delete(make_ctx(turn=1), {"title_query": "Elternabend"})
    fdb.rows = [r for r in fdb.rows if r["calendar_id"] != "family"]
    res = await agent.confirm_delete(make_ctx(turn=2), {"ticket": prep["ticket"]})
    assert res["error"] == "calendar_not_active"


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query,title,ok", [
    ("Zahnarzt", "Zahnarzt Dr. Müller", True),
    ("Zahnarzttermin", "Zahnarzt", True),
    ("den Termin beim Zahnarzt", "Zahnarzt", True),
    ("Friseur", "Zahnarzt", False),
    ("Elternabend Schule", "Elternabend", True),
    ("", "irgendwas", True),
])
def test_title_matches(query, title, ok):
    assert agent.title_matches(query, title) is ok


# ---------------------------------------------------------------------------
# Settings tab overview
# ---------------------------------------------------------------------------
async def test_accounts_overview_marks_and_cleans(basic, fdb, make_ctx):
    fdb.select(CONN_A, "gone-in-google")
    basic.add_connection(CONN_B, "tasks@x.de", scopes=["openid", "email", "https://www.googleapis.com/auth/tasks"])
    res = await agent.accounts_overview(make_ctx())
    a, b = res["accounts"]
    assert a["has_calendar_scope"] and not a["has_other_scopes"]
    assert [c["name"] for c in a["calendars"]][0] == "Privat"      # primary first
    hol = next(c for c in a["calendars"] if c["id"] == "holidays")
    assert hol["read_only"] and hol["is_active"] and not hol["is_default"]
    assert not any(r["calendar_id"] == "gone-in-google" for r in fdb.rows)
    assert not b["has_calendar_scope"] and b["has_other_scopes"] and b["calendars"] is None
    assert res["required_scopes"] == google.CALENDAR_SCOPES


async def test_accounts_overview_reauth(basic, make_ctx):
    basic.token_errors[CONN_A] = google.ReauthRequired(CONN_A)
    res = await agent.accounts_overview(make_ctx())
    assert res["accounts"][0]["status"] == "error"
    assert res["accounts"][0]["calendars_error"] == "reauth_required"


async def test_update_selection_rejects_unknown_calendar(basic, fdb, make_ctx):
    with pytest.raises(agent.SelectionError) as exc:
        await agent.update_selection(make_ctx(), CONN_A, "not-mine", True, None)
    assert exc.value.status == 404
    await agent.update_selection(make_ctx(), CONN_A, "holidays", True, None)
    assert fdb.last_set == (CONN_A, "holidays", True, None, False)


async def test_bug2_non_numeric_duration_is_input_error(basic, make_ctx):
    with pytest.raises(tu.InputError):
        await agent.create_event(make_ctx(), {"title": "X", "date": "2026-10-08", "start_time": "10:00",
                                              "duration_minutes": "abc"})
    basic.add_event(CONN_A, "primary-a", "Zahnarzt", ev_time((2026, 10, 8), 9), ev_time((2026, 10, 8), 10))
    with pytest.raises(tu.InputError):
        await agent.update_event(make_ctx(), {"title_query": "Zahnarzt", "new_duration_minutes": "lang"})
