"""PROJ-99 BUG-4 — get_email_body caps the mail body so long mails cannot
overflow the llama.cpp context mid tool loop."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

# conftest stubs app.tools with a MagicMock for streaming.py — load the real
# module from its file under a private name.
_spec = importlib.util.spec_from_file_location(
    "app._tools_real", Path(__file__).parent.parent / "app" / "tools.py")
tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tools)


@pytest.fixture(autouse=True)
def mail_on(monkeypatch):
    monkeypatch.setattr(tools, "N8N_TOOL_MAIL_URL", "http://n8n:5678/webhook/alice-mail-tools")
    monkeypatch.setattr(tools, "EMAIL_BODY_MAX_CHARS", 100)


def _run(monkeypatch, n8n_result):
    async def fake_call(payload, client):
        return dict(n8n_result)
    monkeypatch.setattr(tools, "_call_n8n_mail", fake_call)
    return asyncio.run(tools.execute_tool(
        "get_email_body", {"mailbox_id": "m", "uid": "1"}, "u", None))


def test_long_body_is_truncated(monkeypatch):
    res = _run(monkeypatch, {"body": "x" * 500})
    assert res["body"] == "x" * 100 + "\n[… gekürzt]"
    assert res["truncated"] is True


def test_short_body_unchanged(monkeypatch):
    res = _run(monkeypatch, {"body": "kurz"})
    assert res == {"body": "kurz"}


def test_error_result_passes_through(monkeypatch):
    res = _run(monkeypatch, {"body": None, "error": "Postfach nicht gefunden"})
    assert res == {"body": None, "error": "Postfach nicht gefunden"}
