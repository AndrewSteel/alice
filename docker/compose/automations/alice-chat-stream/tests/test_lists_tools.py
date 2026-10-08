"""PROJ-106 — routing (calendar / lists / combined), tool forcing and the
server-side guards in lists_tools."""
import asyncio

import pytest

from app import calendar_tools, lists_tools


@pytest.fixture(autouse=True)
def lists_on(monkeypatch):
    monkeypatch.setattr(lists_tools, "LISTS_URL", "http://alice-lists:8010")
    lists_tools._open_questions.clear()


# ---------------------------------------------------------------------------
# classify — spec: Termin/Kalender → calendar; Aufgabe/Frist/fällig/Liste →
# lists; general day query → combined
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("msg, kind", [
    ("Setze Milch, Butter und Eier auf die Einkaufsliste", "lists"),
    ("Setze Salz und Pfeffer auf die Einkaufsliste", "lists"),
    ("Entferne Butter und Eier von der Einkaufsliste", "lists"),
    ("Steht Butter auf der Einkaufsliste?", "lists"),
    ("Was steht auf dem Einkaufszettel?", "lists"),
    ("Neue Aufgabe Reifen wechseln morgen um 14 Uhr", "lists"),
    ("Steuererklärung bis 31. Juli, wichtig", "lists"),
    ("Was ist überfällig?", "lists"),
    ("Was ist heute fällig?", "lists"),
    ("Welche Fristen habe ich diese Woche?", "lists"),
    ("Hake Reifen wechseln ab", "lists"),
    ("Reifen wechseln ist erledigt", "lists"),
    ("Öffne Reifen wechseln wieder", "lists_soft"),
    ("Butter ist doch nicht da", "lists_soft"),
    ("Öffne den Rolladen wieder", "lists_soft"),
    ("Lösche die Aufgabe Reifen wechseln", "lists"),
    ("Leg eine gemeinsame Liste Urlaub an", "lists"),
    ("Welche Listen habe ich?", "lists"),
    ("Setze Dübel auf die Liste Werkstatt", "lists"),
    ("Mach Lidl zur Einkaufsliste", "lists"),
    ("Was habe ich diese Woche erledigt?", "lists"),
    ("Was steht morgen an?", "agenda"),
    ("Was habe ich heute?", "agenda"),
    ("Was liegt heute an?", "agenda"),
    ("Welche Termine habe ich morgen?", "calendar"),
    ("Was habe ich morgen vor?", "calendar"),
    ("Was steht morgen im Kalender an?", "calendar"),
    ("Schalte das Licht im Büro ein", None),
    ("Wie wird das Wetter morgen?", None),
])
def test_classify(msg, kind):
    assert lists_tools.classify(msg) == kind


def test_soft_lists_intent_leaves_ha_fast_first_then_forces():
    # "Öffne den Rolladen wieder" must still reach HA_FAST; when HA_FAST does
    # not match, the request is forced onto the lists tools.
    assert not lists_tools.bypass_fast_path("lists_soft")
    forced = lists_tools.force_decision("Öffne Reifen wechseln wieder", "lists_soft", None)
    assert "lists_reopen_items" in forced


def test_classify_open_question_and_disabled(monkeypatch):
    assert lists_tools.classify("Ja", ("confirm_delete", "lists_remove_items")) == "lists"
    monkeypatch.setattr(lists_tools, "LISTS_URL", "")
    assert lists_tools.classify("Setze Milch auf die Einkaufsliste") is None
    assert not lists_tools.bypass_fast_path("lists")


def test_bypass_fast_path():
    assert lists_tools.bypass_fast_path("lists") and lists_tools.bypass_fast_path("agenda")
    assert not lists_tools.bypass_fast_path("calendar") and not lists_tools.bypass_fast_path(None)


def test_day_query_still_calendar_without_lists():
    # PROJ-87 behaviour is unchanged for the calendar module itself.
    assert calendar_tools.is_calendar_intent("Was steht morgen an?")
    assert not calendar_tools.is_explicit_calendar_intent("Was steht morgen an?")


# ---------------------------------------------------------------------------
# force_decision
# ---------------------------------------------------------------------------
def test_force_lists_request_all_tools_but_confirm_and_agenda():
    forced = lists_tools.force_decision("Setze Milch auf die Einkaufsliste", "lists", None)
    assert "lists_add_items" in forced and "lists_confirm_delete" not in forced and "lists_agenda" not in forced


@pytest.mark.parametrize("msg", ["Was steht auf der Einkaufsliste?", "Welche Listen habe ich?",
                                 "Wie viele Einträge hat die Liste Baumarkt?", "Steht Butter auf der Einkaufsliste?"])
def test_force_questions_read_only(msg):
    assert lists_tools.force_decision(msg, "lists", None) == ["lists_query_items", "lists_manage"]


def test_force_agenda():
    assert lists_tools.force_decision("Was steht morgen an?", "agenda", None) == ["lists_agenda"]


def test_force_after_open_question():
    oq = ("confirm_delete", "lists_remove_items")
    assert lists_tools.force_decision("Ja", "lists", oq) == ["lists_confirm_delete"]
    assert lists_tools.force_decision("Nein", "lists", oq) is None
    assert lists_tools.force_decision("Was?", "lists", oq) is None
    assert lists_tools.force_decision("Ja bitte", "lists", ("unknown_list", "lists_add_items")) == ["lists_add_items"]
    assert lists_tools.force_decision("Nein", "lists", ("unknown_list", "lists_add_items")) is None
    assert lists_tools.force_decision("Ja", "lists", ("confirm_delete_list", "lists_manage")) == ["lists_confirm_delete"]


def test_open_question_tracking():
    lists_tools._track_result("s", "lists_remove_items", {"status": "confirm_delete"})
    assert lists_tools.take_open_question("s") == ("confirm_delete", "lists_remove_items")
    assert lists_tools.take_open_question("s") is None
    lists_tools._track_result("s", "lists_add_items", {"status": "unknown_list"})
    lists_tools._track_result("s", "lists_add_items", {"status": "added"})
    assert lists_tools.take_open_question("s") is None


# ---------------------------------------------------------------------------
# round_tools
# ---------------------------------------------------------------------------
def _names(tools):
    return [t["function"]["name"] for t in tools]


def test_round_tools_forced_first_round_then_all():
    lt = lists_tools.ListsTurn(enabled=True, force_tool=["lists_agenda"])
    ct = calendar_tools.CalendarTurn(enabled=True)
    tools, choice = lists_tools.round_tools([], ct, lt, 1)
    assert _names(tools) == ["lists_agenda"] and choice == "required"
    tools, choice = lists_tools.round_tools([], ct, lt, 2)
    names = _names(tools)
    assert choice is None and "calendar_list_events" in names and "lists_add_items" in names
    assert "lists_agenda" not in names


def test_round_tools_calendar_forcing_kept_and_halt():
    ct = calendar_tools.CalendarTurn(enabled=True, force_tool=["calendar_list_events"])
    lt = lists_tools.ListsTurn(enabled=True)
    tools, choice = lists_tools.round_tools([], ct, lt, 1)
    assert _names(tools) == ["calendar_list_events"] and choice == "required"
    lt.halt_tools = True
    assert lists_tools.round_tools([], ct, lt, 2) == ([], None)


def test_round_tools_lists_disabled_falls_back_to_calendar():
    ct = calendar_tools.CalendarTurn(enabled=False)
    assert lists_tools.round_tools([{"x": 1}], ct, lists_tools.ListsTurn(enabled=False), 1) == ([{"x": 1}], None)
    assert lists_tools.round_tools([{"x": 1}], None, None, 1) == ([{"x": 1}], None)


# ---------------------------------------------------------------------------
# execute guards + agenda
# ---------------------------------------------------------------------------
def _run(coro):
    return asyncio.run(coro)


def test_confirm_delete_requires_explicit_yes(monkeypatch):
    calls = []

    async def fake_call(client, lt, route, args):
        calls.append(route)
        return {"status": "deleted"}
    monkeypatch.setattr(lists_tools, "_call", fake_call)
    lt = lists_tools.ListsTurn(enabled=True, session_id="s", turn=2)
    lists_tools.prepare(lt, "Nein, lieber nicht", "lists", ("confirm_delete", "lists_remove_items"))
    r = _run(lists_tools.execute("lists_confirm_delete", {"ticket": "T"}, None, lt))
    assert r["error"] == "not_confirmed" and calls == []
    lists_tools.prepare(lt, "Ja", "lists", ("confirm_delete", "lists_remove_items"))
    r = _run(lists_tools.execute("lists_confirm_delete", {"ticket": "T"}, None, lt))
    assert r["status"] == "deleted" and calls == ["confirm_delete"]


def test_question_halts_further_tools(monkeypatch):
    async def fake_call(client, lt, route, args):
        return {"status": "confirm_delete", "ticket": "T"}
    monkeypatch.setattr(lists_tools, "_call", fake_call)
    lt = lists_tools.ListsTurn(enabled=True, session_id="s", turn=1, affirmed=True)
    _run(lists_tools.execute("lists_remove_items", {"items": "x"}, None, lt))
    assert lt.halt_tools
    r = _run(lists_tools.execute("lists_confirm_delete", {"ticket": "T"}, None, lt))
    assert r["error"] == "await_user_answer"
    assert lists_tools.take_open_question("s") == ("confirm_delete", "lists_remove_items")


def test_disabled_turn():
    r = _run(lists_tools.execute("lists_add_items", {}, None, lists_tools.ListsTurn(enabled=False)))
    assert r["error"] == "lists_disabled"


def test_agenda_queries_calendar_and_lists(monkeypatch):
    seen = {}

    async def fake_call(client, lt, route, args):
        seen["lists"] = (route, args)
        return {"status": "ok", "items": [], "total": 0}

    async def fake_cal(name, args, client, ct):
        seen["calendar"] = (name, args)
        return {"status": "ok", "events": []}
    monkeypatch.setattr(lists_tools, "_call", fake_call)
    monkeypatch.setattr(calendar_tools, "execute", fake_cal)
    lt = lists_tools.ListsTurn(enabled=True)
    r = _run(lists_tools.execute("lists_agenda", {"range": "tomorrow"}, None, lt,
                                 calendar_tools.CalendarTurn(enabled=True)))
    assert r["status"] == "agenda" and r["calendar"]["status"] == "ok"
    assert seen == {"lists": ("query_items", {"range": "tomorrow"}),
                    "calendar": ("calendar_list_events", {"range": "tomorrow"})}
    seen.clear()
    r = _run(lists_tools.execute("lists_agenda", {"range": "bogus"}, None, lt,
                                 calendar_tools.CalendarTurn(enabled=False)))
    assert r["calendar"] is None and seen == {"lists": ("query_items", {"range": "today"})}
