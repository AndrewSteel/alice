"""PROJ-99: OpenAI-format streaming helpers in streaming.py."""
# conftest.py sets up the stubs; streaming can be imported normally after that.
from app.streaming import _merge_tool_call_delta  # noqa: E402


def test_merges_fragmented_tool_call():
    pending: list[dict] = []
    # First fragment: id + name, no args yet
    _merge_tool_call_delta(pending, {
        "index": 0,
        "id": "call_abc",
        "type": "function",
        "function": {"name": "search_documents", "arguments": ""},
    })
    # Following fragments: argument string split across chunks
    _merge_tool_call_delta(pending, {"index": 0, "function": {"arguments": '{"qu'}})
    _merge_tool_call_delta(pending, {"index": 0, "function": {"arguments": 'ery": "acme"}'}})

    assert len(pending) == 1
    assert pending[0]["id"] == "call_abc"
    assert pending[0]["function"]["name"] == "search_documents"
    assert pending[0]["function"]["arguments"] == '{"query": "acme"}'


def test_synthesises_id_when_backend_omits_it():
    pending: list[dict] = []
    _merge_tool_call_delta(pending, {"index": 0, "function": {"name": "recall", "arguments": "{}"}})
    assert pending[0]["id"] == "call_0"


def test_handles_two_parallel_tool_calls():
    pending: list[dict] = []
    _merge_tool_call_delta(pending, {"index": 0, "id": "a", "function": {"name": "recall", "arguments": "{}"}})
    _merge_tool_call_delta(pending, {"index": 1, "id": "b", "function": {"name": "remember", "arguments": ""}})
    _merge_tool_call_delta(pending, {"index": 1, "function": {"arguments": '{"key":"x","value":"y"}'}})

    assert [tc["id"] for tc in pending] == ["a", "b"]
    assert pending[1]["function"]["arguments"] == '{"key":"x","value":"y"}'


# PROJ-87 live finding: runaway repetition read aloud on the Voice PE.
from app.streaming import LLM_MAX_TOKENS, _is_degenerate  # noqa: E402


def test_repeated_sentence_is_degenerate():
    s = "Falls du eine Bestätigung wünschst, sage ich Bescheid, sobald der Termin gelöscht ist."
    text = "Ich bestätige die Löschung. " + "\n".join([s] * 3) + "\nFalls"
    assert _is_degenerate(text)


def test_normal_answer_is_not_degenerate():
    assert not _is_degenerate("Morgen hast du zwei Termine. Um 9:20 Fußpflege. Um 10 Uhr Test. ")
    assert not _is_degenerate("Ja. Ja. Ja. ")          # short sentences are ignored
    s = "Das ist ein ausreichend langer Satz."
    assert not _is_degenerate(f"{s} {s} ")              # two repeats are allowed
    assert not _is_degenerate(f"{s} {s} {s}")           # last one unfinished → not judged yet


def test_max_tokens_default():
    assert LLM_MAX_TOKENS == 4096
