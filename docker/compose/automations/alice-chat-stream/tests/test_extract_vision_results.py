"""Unit tests for _extract_vision_results() in streaming.py (PROJ-54 QA)."""
# conftest.py sets up the stubs; streaming can be imported normally after that.
from app.streaming import _extract_vision_results  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_search_result(**overrides):
    """Build a minimal alice-tool-search result item."""
    base = {
        "weaviate_id": "aabbccdd-0000-0000-0000-123456789abc",
        "collection": "Invoice",
        "score": 0.85,
        "title_or_summary": "Rechnung von ACME GmbH",
        "date": "2024-01-15",
        "key_fields": {"issuer": "ACME GmbH", "invoiceDate": "2024-01-15"},
        "amount": 499.00,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Happy path — alice-tool-search format
# ---------------------------------------------------------------------------
def test_extracts_from_tool_search_results():
    result = {"results": [_make_search_result()], "error": None}
    items = _extract_vision_results(result)
    assert items is not None
    assert len(items) == 1
    item = items[0]
    assert item["uuid"] == "aabbccdd-0000-0000-0000-123456789abc"
    assert item["document_type"] == "Invoice"
    assert item["summary"] == "Rechnung von ACME GmbH"
    assert item["metadata"]["issuer"] == "ACME GmbH"


def test_extracts_multiple_results():
    result = {
        "results": [
            _make_search_result(collection="Invoice"),
            _make_search_result(weaviate_id="ffffffff-0000-0000-0000-000000000001",
                                collection="BankTransaction"),
        ]
    }
    items = _extract_vision_results(result)
    assert items is not None
    assert len(items) == 2
    assert items[1]["document_type"] == "BankTransaction"


def test_flattens_key_fields_into_metadata():
    result = {"results": [_make_search_result(
        key_fields={"invoiceDate": "2024-03-01", "totalAmount": 120.0}
    )]}
    items = _extract_vision_results(result)
    assert items[0]["metadata"]["invoiceDate"] == "2024-03-01"
    assert items[0]["metadata"]["totalAmount"] == 120.0


# ---------------------------------------------------------------------------
# Fallback — weaviate_uuid / _additional.id
# ---------------------------------------------------------------------------
def test_falls_back_to_weaviate_uuid():
    result = {"results": [
        {"weaviate_uuid": "11111111-2222-3333-4444-555555555555",
         "document_type": "Document", "summary": "test"}
    ]}
    items = _extract_vision_results(result)
    assert items[0]["uuid"] == "11111111-2222-3333-4444-555555555555"


def test_falls_back_to_additional_id():
    result = {"results": [
        {"_additional": {"id": "99999999-aaaa-bbbb-cccc-dddddddddddd"},
         "collection": "Email", "summary": "test"}
    ]}
    items = _extract_vision_results(result)
    assert items[0]["uuid"] == "99999999-aaaa-bbbb-cccc-dddddddddddd"


# ---------------------------------------------------------------------------
# Alternative container key names
# ---------------------------------------------------------------------------
def test_finds_results_under_hits():
    result = {"hits": [_make_search_result()]}
    items = _extract_vision_results(result)
    assert items is not None


def test_finds_results_under_documents():
    result = {"documents": [_make_search_result()]}
    items = _extract_vision_results(result)
    assert items is not None


# ---------------------------------------------------------------------------
# Edge cases — no vision results
# ---------------------------------------------------------------------------
def test_returns_none_when_no_results_key():
    assert _extract_vision_results({"answer": "Paris"}) is None


def test_returns_none_when_results_empty():
    assert _extract_vision_results({"results": []}) is None


def test_returns_none_when_no_uuid():
    result = {"results": [{"collection": "Invoice", "summary": "x"}]}
    assert _extract_vision_results(result) is None


def test_skips_non_dict_items():
    result = {"results": ["not_a_dict", _make_search_result()]}
    items = _extract_vision_results(result)
    assert items is not None
    assert len(items) == 1


def test_returns_none_when_all_items_lack_uuid():
    result = {"results": [{"collection": "Invoice"}, {"score": 0.5}]}
    assert _extract_vision_results(result) is None


# ---------------------------------------------------------------------------
# title_or_summary vs summary precedence
# ---------------------------------------------------------------------------
def test_prefers_title_or_summary_over_summary():
    result = {"results": [
        {**_make_search_result(),
         "title_or_summary": "TOS value",
         "summary": "summary value"}
    ]}
    items = _extract_vision_results(result)
    assert items[0]["summary"] == "TOS value"


def test_falls_back_to_summary_when_no_title_or_summary():
    item = {k: v for k, v in _make_search_result().items()
            if k != "title_or_summary"}
    item["summary"] = "just summary"
    result = {"results": [item]}
    items = _extract_vision_results(result)
    assert items[0]["summary"] == "just summary"


def test_summary_is_none_when_absent():
    item = {k: v for k, v in _make_search_result().items()
            if k not in ("title_or_summary", "summary", "ai_summary")}
    result = {"results": [item]}
    items = _extract_vision_results(result)
    assert items[0]["summary"] is None
