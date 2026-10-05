"""PROJ-87: calendar tool gating, turn start and forwarding in alice-chat-stream."""
import asyncio
import json
import sys

import pytest

from app import calendar_tools as ct


class _TimeoutExc(Exception):
    pass


# conftest stubs httpx with a MagicMock — give the except clause a real class.
sys.modules["httpx"].TimeoutException = _TimeoutExc


class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class _Client:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.exc:
            raise self.exc
        return self.resp


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def calendar_url(monkeypatch):
    monkeypatch.setattr(ct, "CALENDAR_URL", "http://alice-calendar:8009")


def test_channel_for_voice_sources():
    assert ct.channel_for("esphome") == "voice"
    assert ct.channel_for("esphome:Büro") == "voice"
    assert ct.channel_for("webapp_mic") == "chat"
    assert ct.channel_for(None) == "chat"


def test_start_turn_enabled_with_pending():
    pending = {"tool": "delete_event", "result": {"status": "confirm_delete", "ticket": "T1"}}
    client = _Client(_Resp(200, {"enabled": True, "reason": None, "pending": pending}))
    turn = run(ct.start_turn(client, "jwt", "s1", 4, "esphome:Büro"))
    assert turn.enabled and turn.channel == "voice" and turn.turn == 4
    text = "\n".join(turn.prompt_lines)
    assert "calendar_" in text and '"ticket": "T1"' in text
    assert client.calls[0]["url"].endswith("/internal/turn")
    assert client.calls[0]["headers"]["Authorization"] == "Bearer jwt"
    assert client.calls[0]["json"] == {"session_id": "s1", "turn": 4}


def test_start_turn_forbidden_and_unknown_speaker():
    forb = run(ct.start_turn(_Client(_Resp(200, {"enabled": False, "reason": "forbidden"})), "j", "s", 1, None))
    assert not forb.enabled and "keinen Kalenderzugriff" in "\n".join(forb.prompt_lines)
    unk = run(ct.start_turn(_Client(_Resp(200, {"enabled": False, "reason": "unknown_speaker"})), "j", "s", 1, None))
    assert not unk.enabled and "nicht erkannt" in "\n".join(unk.prompt_lines)


def test_start_turn_service_down_never_raises():
    turn = run(ct.start_turn(_Client(exc=RuntimeError("down")), "j", "s", 1, None))
    assert not turn.enabled and "nicht erreichbar" in "\n".join(turn.prompt_lines)
    turn = run(ct.start_turn(_Client(_Resp(500, None)), "j", "s", 1, None))
    assert not turn.enabled


def test_feature_off_without_url(monkeypatch):
    monkeypatch.setattr(ct, "CALENDAR_URL", "")
    client = _Client(_Resp(200, {"enabled": True}))
    turn = run(ct.start_turn(client, "j", "s", 1, None))
    assert not turn.enabled and turn.prompt_lines == [] and client.calls == []


def test_execute_forwards_session_turn_channel_and_token():
    client = _Client(_Resp(200, {"status": "created", "event": {"title": "Zahnarzt"}}))
    turn = ct.CalendarTurn(enabled=True, token="jwt", session_id="s1", turn=7, channel="voice")
    res = run(ct.execute("calendar_create_event", {"title": "Zahnarzt"}, client, turn))
    assert res["status"] == "created"
    call = client.calls[0]
    assert call["url"] == "http://alice-calendar:8009/internal/tools/create_event"
    assert call["json"] == {"args": {"title": "Zahnarzt"}, "session_id": "s1", "turn": 7, "channel": "voice"}
    assert call["headers"]["Authorization"] == "Bearer jwt"


def test_execute_refuses_when_disabled():
    client = _Client(_Resp(200, {"status": "created"}))
    res = run(ct.execute("calendar_create_event", {}, client, ct.CalendarTurn(enabled=False)))
    assert res["error"] == "calendar_disabled" and client.calls == []


@pytest.mark.parametrize("client", [
    _Client(exc=_TimeoutExc()),
    _Client(exc=RuntimeError("conn refused")),
    _Client(_Resp(502, None)),
    _Client(_Resp(200, ValueError("bad json"))),
])
def test_execute_failures_are_errors_never_success(client):
    res = run(ct.execute("calendar_confirm_delete", {"ticket": "x"}, client,
                         ct.CalendarTurn(enabled=True, token="j", session_id="s", turn=1)))
    assert "error" in res and "status" not in res


def test_schema_names_match_routes():
    names = {t["function"]["name"] for t in ct.schema()}
    assert names == set(ct.TOOL_ROUTES)
    json.dumps(ct.schema())  # serialisable for the LLM payload


def test_summaries():
    assert ct.tool_summary("calendar_list_events", {"status": "ok", "total": 0}) == "Keine Termine"
    assert ct.tool_summary("calendar_list_events", {"status": "ok", "total": 3}) == "3 Termine"
    assert ct.tool_summary("calendar_confirm_delete", {"status": "deleted"}) == "Termin gelöscht"
    assert ct.tool_status("calendar_create_event", {"title": "Zahnarzt"}) == "Lege Termin 'Zahnarzt' an…"


# ---------------------------------------------------------------------------
# Live finding 2026-10-05: HA fast-path capture + tool-less hallucination
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("msg,expected", [
    ("Welche Termine habe ich morgen?", True),
    ("Welche Termine habe ich in meinem Kalender für morgen?", True),
    ("Erstelle einen Kalendereintrag für morgen um 10.00 Uhr", True),
    ("Wann ist mein nächster Termin?", True),
    ("Was steht morgen an?", True),
    ("Was habe ich am Freitag vor?", True),
    ("Stelle einen Timer auf 10 Minuten", False),
    ("Schalte das Licht im Büro ein", False),
    ("Nein", False),
])
def test_calendar_intent(msg, expected):
    assert ct.is_calendar_intent(msg) is expected


def test_open_question_is_consumed_by_next_request_only():
    turn = ct.CalendarTurn(enabled=True, token="j", session_id="sess-q", turn=3)
    run(ct.execute("calendar_delete_event", {"title_query": "Zahnarzt"},
                   _Client(_Resp(200, {"status": "confirm_delete", "ticket": "T"})), turn))
    assert ct.take_open_question("sess-q") == ("confirm_delete", "calendar_delete_event")
    assert ct.take_open_question("sess-q") is None


def test_completed_action_clears_open_question():
    ask = ct.CalendarTurn(enabled=True, token="j", session_id="sess-c", turn=3)
    run(ct.execute("calendar_update_event", {}, _Client(_Resp(200, {"status": "ambiguous"})), ask))
    done = ct.CalendarTurn(enabled=True, token="j", session_id="sess-c", turn=4)
    run(ct.execute("calendar_update_event", {}, _Client(_Resp(200, {"status": "updated"})), done))
    assert ct.take_open_question("sess-c") is None


def test_bypass_fast_path_for_calendar_and_open_questions():
    assert ct.bypass_fast_path("Welche Termine habe ich morgen?", None)
    assert ct.bypass_fast_path("Nein", ("confirm_delete", "calendar_delete_event"))  # was a switch intent
    assert ct.bypass_fast_path("den zweiten", ("ambiguous", "calendar_update_event"))
    assert not ct.bypass_fast_path("Licht an", None)


def test_bypass_off_without_calendar_service(monkeypatch):
    monkeypatch.setattr(ct, "CALENDAR_URL", "")
    assert not ct.bypass_fast_path("Welche Termine habe ich morgen?", None)


# ---------------------------------------------------------------------------
# Live finding 2026-10-05 (2): wrong forced tool, same-request confirm loop
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("msg,tool", [
    ("Lösche den Termin morgen 10 Uhr mit dem Titel Test", "calendar_delete_event"),
    ("Löscheten den Termin morgen 10 Uhr mit dem Titel Test.", "calendar_delete_event"),
    ("Lösche den Kalendereintrag von morgen", "calendar_delete_event"),
    ("Sag den Termin beim Zahnarzt ab", "calendar_delete_event"),
    ("Verschiebe den Zahnarzttermin auf 11 Uhr", "calendar_update_event"),
    ("Benenne den Termin um in Arzt", "calendar_update_event"),
    ("Trage einen Termin für morgen 10 Uhr mit dem Titel Test ein", "calendar_create_event"),
    ("Erstelle einen Kalendereintrag für morgen um 10.00 Uhr", "calendar_create_event"),
    ("Lege morgen einen Termin Zahnarzt an", "calendar_create_event"),
    ("Welche Termine habe ich morgen?", "calendar_list_events"),
    ("Was steht morgen an?", "calendar_list_events"),
])
def test_force_decision_picks_action_tool(msg, tool):
    assert ct.force_decision(msg, None) == [tool]


@pytest.mark.parametrize("msg,open_q,expected", [
    ("Ja, löschen.", ("confirm_delete", "calendar_delete_event"), "calendar_confirm_delete"),
    ("Ja", ("confirm_delete", "calendar_delete_event"), "calendar_confirm_delete"),
    ("Nein", ("confirm_delete", "calendar_delete_event"), None),
    ("den zweiten", ("ambiguous", "calendar_update_event"), "calendar_update_event"),
    ("nur diesen", ("needs_scope", "calendar_delete_event"), "calendar_delete_event"),
    ("Familie", ("needs_calendar", "calendar_create_event"), "calendar_create_event"),
    ("Ja", ("confirm_past", "calendar_create_event"), "calendar_create_event"),
])
def test_force_decision_on_open_question(msg, open_q, expected):
    assert ct.force_decision(msg, open_q) == ([expected] if expected else None)


def test_forced_round_offers_only_that_tool():
    base = [{"type": "function", "function": {"name": "recall"}}]
    tl, choice = ct.round_tools(base, ct.CalendarTurn(enabled=True, force_tool=["calendar_delete_event"]), 1)
    assert choice == "required" and [t["function"]["name"] for t in tl] == ["calendar_delete_event"]


def test_question_halts_further_tools_in_same_request():
    turn = ct.CalendarTurn(enabled=True, token="j", session_id="sess-h", turn=5)
    client = _Client(_Resp(200, {"status": "confirm_delete", "ticket": "T"}))
    run(ct.execute("calendar_delete_event", {"title_query": "Test"}, client, turn))
    assert turn.halt_tools
    assert ct.round_tools([{"type": "function", "function": {"name": "recall"}}], turn, 2) == ([], None)
    # a parallel / follow-up confirm in the same request never reaches alice-calendar
    res = run(ct.execute("calendar_confirm_delete", {"ticket": "T"}, client, turn))
    assert res["error"] == "await_user_answer" and len(client.calls) == 1
    assert ct.take_open_question("sess-h") == ("confirm_delete", "calendar_delete_event")


def test_voice_prompt_has_no_markdown_rule():
    voice = run(ct.start_turn(_Client(_Resp(200, {"enabled": True})), "j", "s", 1, "esphome:Büro"))
    chat = run(ct.start_turn(_Client(_Resp(200, {"enabled": True})), "j", "s", 1, "webapp_cc"))
    assert any("vorgelesen" in l for l in voice.prompt_lines)
    assert not any("vorgelesen" in l for l in chat.prompt_lines)
    assert any("KURZ" in l for l in chat.prompt_lines)



# ---------------------------------------------------------------------------
# Live finding 2026-10-05 (4): "Setze einen Termin …" was forced to listing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("msg,tools", [
    ("Setze einen Termin für Mittwoch um 11.00 Uhr mit dem Titel Zahnarzt. Dauer 30 Minuten.",
     ["calendar_create_event"]),
    ("Notiere einen Termin am Freitag beim Friseur", ["calendar_create_event"]),
    ("Merk dir einen Termin morgen um 8", ["calendar_create_event"]),
    ("Termin am Freitag 14 Uhr Friseur", ["calendar_create_event", "calendar_list_events"]),
    ("Habe ich am Mittwoch einen Termin?", ["calendar_list_events"]),
    ("Zeig mir meine Termine für nächste Woche", ["calendar_list_events"]),
    ("Gibt es morgen Termine", ["calendar_list_events"]),
])
def test_detect_action_create_variants_and_fallback(msg, tools):
    assert ct.force_decision(msg, None) == tools


def test_unclear_request_offers_create_and_list():
    tl, choice = ct.round_tools([], ct.CalendarTurn(
        enabled=True, force_tool=["calendar_create_event", "calendar_list_events"]), 1)
    assert choice == "required"
    assert {t["function"]["name"] for t in tl} == {"calendar_create_event", "calendar_list_events"}
