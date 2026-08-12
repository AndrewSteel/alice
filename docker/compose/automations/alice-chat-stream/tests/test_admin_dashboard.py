"""Unit tests for app/admin_dashboard.py (PROJ-77 QA)."""
# conftest.py sets up the stubs; admin_dashboard can be imported normally after that.
from app.admin_dashboard import (  # noqa: E402
    _execution_url,
    _shape_failed,
    _shape_running,
    _shape_weaviate_schemas,
    _split_window,
)


# ---------------------------------------------------------------------------
# Weaviate schema shaping (AC-C1, AC-C4)
# ---------------------------------------------------------------------------
def test_shapes_schemas_with_counts():
    classes = ["Invoice", "AliceMemory"]
    aggregate = {
        "Invoice": [{"meta": {"count": 42}}],
        "AliceMemory": [{"meta": {"count": 7}}],
    }
    result = _shape_weaviate_schemas(classes, aggregate)
    assert result == [
        {"name": "Invoice", "count": 42},
        {"name": "AliceMemory", "count": 7},
    ]


def test_shapes_schemas_missing_aggregate_entry_as_zero():
    result = _shape_weaviate_schemas(["Empty"], {})
    assert result == [{"name": "Empty", "count": 0}]


def test_shapes_no_classes_as_empty_list():
    assert _shape_weaviate_schemas([], {}) == []


# ---------------------------------------------------------------------------
# n8n execution URL building (AC-E4, AC-F3)
# ---------------------------------------------------------------------------
def test_execution_url_uses_public_n8n_host():
    url = _execution_url("wf123", "exec456")
    assert url.startswith("https://n8n.happy-mining.de/")
    assert "wf123" in url
    assert "exec456" in url


# ---------------------------------------------------------------------------
# n8n execution shaping (AC-E1/E2, AC-F1/F2)
# ---------------------------------------------------------------------------
def test_shapes_running_executions():
    executions = [{"id": "1", "workflowId": "wf1", "startedAt": "2026-08-12T10:00:00.000Z"}]
    names = {"wf1": "alice-dms-path-worker"}
    result = _shape_running(executions, names)
    assert result == [
        {
            "id": "1",
            "workflow_id": "wf1",
            "workflow_name": "alice-dms-path-worker",
            "started_at": "2026-08-12T10:00:00.000Z",
            "url": _execution_url("wf1", "1"),
        }
    ]


def test_shapes_running_execution_falls_back_to_id_when_name_unresolved():
    executions = [{"id": "1", "workflowId": "wf1", "startedAt": "2026-08-12T10:00:00.000Z"}]
    result = _shape_running(executions, {})
    assert result[0]["workflow_name"] == "wf1"


def test_shapes_failed_executions_uses_stopped_at():
    executions = [
        {
            "id": "2",
            "workflowId": "wf2",
            "startedAt": "2026-08-12T09:00:00.000Z",
            "stoppedAt": "2026-08-12T09:05:00.000Z",
        }
    ]
    result = _shape_failed(executions, {"wf2": "alice-mail-sync"})
    assert result[0]["failed_at"] == "2026-08-12T09:05:00.000Z"


def test_shapes_failed_execution_falls_back_to_started_at_when_no_stopped_at():
    executions = [{"id": "2", "workflowId": "wf2", "startedAt": "2026-08-12T09:00:00.000Z"}]
    result = _shape_failed(executions, {})
    assert result[0]["failed_at"] == "2026-08-12T09:00:00.000Z"


# ---------------------------------------------------------------------------
# 7-day window pagination cutoff (AC-F1, Technical Requirements)
# ---------------------------------------------------------------------------
def test_split_window_keeps_entries_within_cutoff():
    executions = [
        {"id": "1", "startedAt": "2026-08-12T10:00:00.000Z"},
        {"id": "2", "startedAt": "2026-08-10T10:00:00.000Z"},
    ]
    in_window, reached_end = _split_window(executions, cutoff_iso="2026-08-05T00:00:00.000Z")
    assert [e["id"] for e in in_window] == ["1", "2"]
    assert reached_end is False


def test_split_window_stops_at_first_entry_older_than_cutoff():
    executions = [
        {"id": "1", "startedAt": "2026-08-12T10:00:00.000Z"},
        {"id": "2", "startedAt": "2026-08-01T10:00:00.000Z"},  # older than cutoff
        {"id": "3", "startedAt": "2026-07-01T10:00:00.000Z"},
    ]
    in_window, reached_end = _split_window(executions, cutoff_iso="2026-08-05T00:00:00.000Z")
    assert [e["id"] for e in in_window] == ["1"]
    assert reached_end is True


def test_split_window_empty_page():
    in_window, reached_end = _split_window([], cutoff_iso="2026-08-05T00:00:00.000Z")
    assert in_window == []
    assert reached_end is False
