"""PROJ-87: end-to-end stream_chat with a fake LLM — templated calendar reply, no second round."""
import asyncio
import json
import sys

from app import calendar_tools, streaming


class _Exc(Exception):
    pass


class _FakeStreamResp:
    status_code = 200

    def __init__(self, frames):
        self._frames = frames

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for f in self._frames:
            yield "data: " + json.dumps(f)
        yield "data: [DONE]"


class _FakeLLMClient:
    """Each stream() call pops the next scripted LLM round."""
    rounds: list = []
    payloads: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, json=None, headers=None):
        _FakeLLMClient.payloads.append(json)
        return _FakeStreamResp(_FakeLLMClient.rounds.pop(0))


def _tool_call_round(name, args):
    return [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}}]}, "finish_reason": "tool_calls"}]}]


def _text_round(text):
    return [{"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}]


def _run(monkeypatch, rounds, tool_result, ct):
    monkeypatch.setattr(streaming.httpx, "AsyncClient", _FakeLLMClient, raising=False)
    monkeypatch.setattr(streaming.httpx, "TimeoutException", _Exc, raising=False)
    monkeypatch.setattr(streaming.httpx, "HTTPError", _Exc, raising=False)
    _FakeLLMClient.rounds = list(rounds)
    _FakeLLMClient.payloads = []
    streaming.tools.tool_schema.return_value = []

    async def fake_execute(name, args, client, turn):
        fake_execute.calls.append((name, args))
        return tool_result
    fake_execute.calls = []
    monkeypatch.setattr(calendar_tools, "execute", fake_execute)

    async def collect():
        out = []
        async for sse, _side in streaming.stream_chat(user_message="Ja.", history=[], system_prompt="s",
                                                       user_id="u", calendar=ct):
            out.append(sse.decode())
        return out
    return asyncio.run(collect()), fake_execute.calls


def _tokens(events):
    return "".join(json.loads(e[6:])["content"] for e in events
                   if e.startswith("data: {") and json.loads(e[6:]).get("type") == "token")


def test_confirm_delete_answered_from_template_without_second_round(monkeypatch):
    ct = calendar_tools.CalendarTurn(enabled=True, force_tool=["calendar_confirm_delete"], channel="voice",
                                     session_id="s", turn=2, lang="de")
    result = {"status": "deleted", "scope": "single",
              "event": {"title": "Test", "date": "2026-10-06", "all_day": False, "start_time": "10:00"}}
    # a second round is scripted but must never be requested
    events, calls = _run(monkeypatch, [_tool_call_round("calendar_confirm_delete", {"ticket": "T"}),
                                       _text_round("Ich lösche ... wurde erfolgreich gelöscht.")], result, ct)
    assert calls == [("calendar_confirm_delete", {"ticket": "T"})]
    assert _tokens(events) == "Ich habe den Termin „Test“ gelöscht."
    assert len(_FakeLLMClient.payloads) == 1
    first = _FakeLLMClient.payloads[0]
    assert first["tool_choice"] == "required"
    assert [t["function"]["name"] for t in first["tools"]] == ["calendar_confirm_delete"]
    assert any('"conversation_end"' in e for e in events)        # voice session may end


def test_question_keeps_conversation_open(monkeypatch):
    ct = calendar_tools.CalendarTurn(enabled=True, force_tool=["calendar_delete_event"], channel="voice",
                                     session_id="s", turn=1, lang="de")
    result = {"status": "confirm_delete", "ticket": "T", "scope": "single",
              "event": {"title": "Test", "date": "2026-10-06", "all_day": False, "start_time": "10:00"}}
    events, _ = _run(monkeypatch, [_tool_call_round("calendar_delete_event", {"title_query": "Test"})], result, ct)
    assert _tokens(events).startswith("Soll ich „Test“")
    assert not any('"conversation_end"' in e for e in events)


def test_invalid_input_goes_back_to_llm(monkeypatch):
    ct = calendar_tools.CalendarTurn(enabled=True, force_tool=["calendar_create_event"], session_id="s", turn=1)
    events, _ = _run(monkeypatch, [_tool_call_round("calendar_create_event", {"title": "x"}),
                                   _text_round("Für welches Datum?")],
                     {"error": "invalid_input", "message": "date ist erforderlich"}, ct)
    assert _tokens(events) == "Für welches Datum?" and len(_FakeLLMClient.payloads) == 2



def _text_and_tool_round(text, name, args):
    return [{"choices": [{"delta": {"content": text}}]}] + _tool_call_round(name, args)


def test_text_before_forced_tool_call_is_not_streamed(monkeypatch):
    """Live: an invented reminder question was read aloud before list_events ran."""
    ct = calendar_tools.CalendarTurn(enabled=True, force_tool=["calendar_create_event"], channel="voice",
                                     session_id="s", turn=1, lang="de")
    result = {"status": "created", "event": {"title": "Zahnarzt", "date": "2026-10-07", "all_day": False,
                                             "start_time": "11:00", "calendar": "Privatkalender"}}
    events, _ = _run(monkeypatch, [_text_and_tool_round(
        "Möchtest du, dass ich dir eine Erinnerung einrichte? (Der Termin wird erst angelegt, wenn du bestätigst.)",
        "calendar_create_event", {"title": "Zahnarzt", "date": "2026-10-07", "start_time": "11:00"})], result, ct)
    text = _tokens(events)
    assert "Erinnerung" not in text
    assert text == "Ich habe „Zahnarzt“ am Mittwoch, 7. Oktober um 11 Uhr in den Kalender „Privatkalender“ eingetragen." \
        or text.startswith("Ich habe „Zahnarzt“")


def test_forced_round_without_tool_call_falls_back_to_free_answer(monkeypatch):
    ct = calendar_tools.CalendarTurn(enabled=True, force_tool=["calendar_list_events"], session_id="s", turn=1)
    events, calls = _run(monkeypatch, [_text_round("dropped"), _text_round("Freie Antwort.")], {}, ct)
    assert calls == [] and _tokens(events) == "Freie Antwort." and len(_FakeLLMClient.payloads) == 2
    assert "tool_choice" not in _FakeLLMClient.payloads[1]
