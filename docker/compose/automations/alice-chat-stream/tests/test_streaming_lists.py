"""PROJ-106: end-to-end stream_chat with a fake LLM — forced lists tool,
templated reply, voice conversation_end, delete guard."""
import asyncio
import json

from app import calendar_tools, lists_tools, streaming
from tests.test_streaming_calendar import (
    _Exc, _FakeLLMClient, _text_and_tool_round, _text_round, _tokens, _tool_call_round,
)


def _run(monkeypatch, rounds, results, lt, ct=None, message="x"):
    monkeypatch.setattr(streaming.httpx, "AsyncClient", _FakeLLMClient, raising=False)
    monkeypatch.setattr(streaming.httpx, "TimeoutException", _Exc, raising=False)
    monkeypatch.setattr(streaming.httpx, "HTTPError", _Exc, raising=False)
    monkeypatch.setattr(lists_tools, "LISTS_URL", "http://alice-lists:8010")
    _FakeLLMClient.rounds = list(rounds)
    _FakeLLMClient.payloads = []
    streaming.tools.tool_schema.return_value = []
    calls = []

    async def fake_call(client, turn, route, args):
        calls.append((route, args))
        return results.pop(0)
    monkeypatch.setattr(lists_tools, "_call", fake_call)

    async def collect():
        out = []
        async for sse, _side in streaming.stream_chat(user_message=message, history=[], system_prompt="s",
                                                       user_id="u", calendar=ct, lists=lt):
            out.append(sse.decode())
        return out
    return asyncio.run(collect()), calls


def _turn(message, kind, open_question=None, channel="chat", turn=1):
    lt = lists_tools.ListsTurn(enabled=True, session_id="s", turn=turn, channel=channel, lang="de")
    lists_tools.prepare(lt, message, kind, open_question)
    return lt


def test_shopping_add_forced_and_templated(monkeypatch):
    msg = "Setze Milch, Butter und Eier auf die Einkaufsliste"
    lt = _turn(msg, "lists", channel="voice")
    result = {"status": "added", "list": {"name": "Einkaufsliste", "shared": True, "shopping": True},
              "items": [{"title": "Milch"}, {"title": "Butter"}, {"title": "Eier"}], "reopened": []}
    events, calls = _run(monkeypatch, [
        _text_and_tool_round("Klar, mache ich!", "lists_add_items",
                             {"items": "Milch, Butter und Eier", "list": "Einkaufsliste"}),
        _text_round("Ich habe Milch hinzugefügt (erfunden)."),
    ], [result], lt, message=msg)
    assert calls == [("add_items", {"items": "Milch, Butter und Eier", "list": "Einkaufsliste"})]
    assert _tokens(events) == "Ich habe Milch, Butter und Eier auf die Einkaufsliste gesetzt."
    first = _FakeLLMClient.payloads[0]
    assert first["tool_choice"] == "required"
    assert "lists_add_items" in [t["function"]["name"] for t in first["tools"]]
    assert len(_FakeLLMClient.payloads) == 1                       # no second LLM round
    assert any('"conversation_end"' in e for e in events)


def test_delete_question_keeps_voice_open_and_halts(monkeypatch):
    msg = "Lösche die Aufgabe Reifen wechseln"
    lt = _turn(msg, "lists", channel="voice")
    q = {"status": "confirm_delete", "ticket": "T", "item": {"title": "Reifen wechseln"},
         "list": {"name": "Meine Aufgaben", "shopping": False}, "removed": [], "not_found": [], "deferred": []}
    # The model tries to confirm in the same request — must not run.
    rounds = [[{"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "c1", "type": "function",
         "function": {"name": "lists_remove_items", "arguments": json.dumps({"items": "Reifen wechseln"})}},
        {"index": 1, "id": "c2", "type": "function",
         "function": {"name": "lists_confirm_delete", "arguments": json.dumps({"ticket": "T"})}},
    ]}, "finish_reason": "tool_calls"}]}]]
    events, calls = _run(monkeypatch, rounds, [q], lt, message=msg)
    assert calls == [("remove_items", {"items": "Reifen wechseln"})]
    assert _tokens(events) == "Soll ich „Reifen wechseln“ von der Liste „Meine Aufgaben“ löschen?"
    assert not any('"conversation_end"' in e for e in events)


def test_yes_confirms_delete_next_turn(monkeypatch):
    lt = _turn("Ja", "lists", ("confirm_delete", "lists_remove_items"), turn=2)
    assert lt.force_tool == ["lists_confirm_delete"]
    events, calls = _run(monkeypatch, [_tool_call_round("lists_confirm_delete", {"ticket": "T"})],
                         [{"status": "deleted", "kind": "item", "item": {"title": "Reifen wechseln"}}], lt,
                         message="Ja")
    assert calls == [("confirm_delete", {"ticket": "T"})]
    assert _tokens(events) == "Ich habe „Reifen wechseln“ gelöscht."


def test_no_never_deletes(monkeypatch):
    lt = _turn("Nein", "lists", ("confirm_delete", "lists_remove_items"), turn=2)
    assert lt.force_tool is None
    # Even if the model calls confirm on its own, the guard refuses.
    events, calls = _run(monkeypatch, [_tool_call_round("lists_confirm_delete", {"ticket": "T"})], [], lt,
                         message="Nein")
    assert calls == []
    assert _tokens(events) == "Okay, ich habe nichts gelöscht."


def test_agenda_combines_calendar_and_lists(monkeypatch):
    msg = "Was steht morgen an?"
    lt = _turn(msg, "agenda")
    ct = calendar_tools.CalendarTurn(enabled=True, session_id="s", turn=1, lang="de")

    async def fake_cal(name, args, client, turn):
        return {"status": "ok", "range": {"from": "2030-01-02", "to": "2030-01-02"},
                "events": [{"title": "Zahnarzt", "date": "2030-01-02", "all_day": False, "start_time": "10:00"}],
                "total": 1}
    monkeypatch.setattr(calendar_tools, "execute", fake_cal)
    events, calls = _run(monkeypatch, [_tool_call_round("lists_agenda", {"range": "tomorrow"})],
                         [{"status": "ok", "range": {"keyword": "tomorrow"}, "total": 1,
                           "items": [{"title": "Reifen wechseln"}]}], lt, ct, message=msg)
    text = _tokens(events)
    assert "Zahnarzt" in text and "„Reifen wechseln“" in text
    assert text.index("Zahnarzt") < text.index("Reifen")
    first = _FakeLLMClient.payloads[0]
    assert [t["function"]["name"] for t in first["tools"]] == ["lists_agenda"]


def test_invalid_input_goes_back_to_llm(monkeypatch):
    lt = _turn("Steuererklärung bis 31. Juli, wichtig", "lists")
    events, calls = _run(monkeypatch, [
        _tool_call_round("lists_add_items", {"items": "Steuererklärung", "deadline_date": "31. Juli"}),
        _tool_call_round("lists_add_items", {"items": "Steuererklärung", "deadline_date": "2027-07-31",
                                             "priority": "high"}),
    ], [{"error": "invalid_input", "message": "deadline_date muss im Format YYYY-MM-DD angegeben werden"},
        {"status": "added", "list": {"name": "Meine Aufgaben", "shopping": False}, "reopened": [],
         "items": [{"title": "Steuererklärung", "deadline": {"date": "2027-07-31"}, "priority": "high"}]}],
        lt, message="Steuererklärung bis 31. Juli, wichtig")
    assert len(calls) == 2
    assert _tokens(events).startswith("Ich habe „Steuererklärung“ auf die Liste „Meine Aufgaben“ gesetzt, Frist bis")


def test_parallel_tool_calls_all_confirmed(monkeypatch):
    """QA BUG-1: the model split the items itself — every stored entry is confirmed."""
    msg = "Setze Milch und Butter auf die Einkaufsliste"
    lt = _turn(msg, "lists", channel="voice")
    shop = {"name": "Einkaufsliste", "shared": True, "shopping": True}
    rounds = [[{"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "c1", "type": "function",
         "function": {"name": "lists_add_items", "arguments": json.dumps({"items": "Milch", "list": "Einkaufsliste"})}},
        {"index": 1, "id": "c2", "type": "function",
         "function": {"name": "lists_add_items", "arguments": json.dumps({"items": "Butter", "list": "Einkaufsliste"})}},
    ]}, "finish_reason": "tool_calls"}]}]]
    events, calls = _run(monkeypatch, rounds, [
        {"status": "added", "list": shop, "items": [{"title": "Milch"}], "reopened": []},
        {"status": "added", "list": shop, "items": [{"title": "Butter"}], "reopened": []},
    ], lt, message=msg)
    assert len(calls) == 2
    assert _tokens(events) == ("Ich habe Milch auf die Einkaufsliste gesetzt. "
                               "Ich habe Butter auf die Einkaufsliste gesetzt.")
    assert any('"conversation_end"' in e for e in events)


def test_parallel_calls_with_question_keep_conversation_open(monkeypatch):
    lt = _turn("x", "lists", channel="voice")
    rounds = [[{"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "c1", "type": "function",
         "function": {"name": "lists_add_items", "arguments": json.dumps({"items": "A"})}},
        {"index": 1, "id": "c2", "type": "function",
         "function": {"name": "lists_add_items", "arguments": json.dumps({"items": "B", "list": "Werkstatt"})}},
    ]}, "finish_reason": "tool_calls"}]}]]
    events, _ = _run(monkeypatch, rounds, [
        {"status": "added", "list": {"name": "Meine Aufgaben"}, "items": [{"title": "A"}], "reopened": []},
        {"status": "unknown_list", "name": "Werkstatt"},
    ], lt)
    assert _tokens(events).endswith("Soll ich sie anlegen?")
    assert not any('"conversation_end"' in e for e in events)
