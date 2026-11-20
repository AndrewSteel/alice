"""PROJ-121 — documents, images and mails only for admin / haushalt.

Guests and unrecognised speakers (voice-guest) neither get the archive tools
offered nor executed, and the system prompt tells the model to decline in the
user's language (AK-5, AK-6, AK-7, AK-10)."""
import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# conftest stubs app.tools with a MagicMock for streaming.py — load the real
# module from its file under a private name (same as test_mail_tools.py).
_spec = importlib.util.spec_from_file_location(
    "app._tools_archive", Path(__file__).parent.parent / "app" / "tools.py")
tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tools)

ARCHIVE = {"search_documents", "get_document_details", "search_images", "search_emails", "get_email_body"}


@pytest.fixture(autouse=True)
def urls(monkeypatch):
    monkeypatch.setattr(tools, "N8N_TOOL_MAIL_URL", "http://n8n/webhook/mail")
    monkeypatch.setattr(tools, "N8N_TOOL_HA_URL", "http://n8n/webhook/ha")
    monkeypatch.setattr(tools, "N8N_TOOL_SEARCH_URL", "http://n8n/webhook/search")


def _names(schema):
    return {t["function"]["name"] for t in schema}


def test_household_gets_all_archive_tools():
    assert ARCHIVE <= _names(tools.tool_schema(True))


def test_guest_gets_no_archive_tools_but_home_assistant():
    names = _names(tools.tool_schema(False))
    assert not names & ARCHIVE
    assert "home_assistant" in names
    # default is the safe one
    assert not _names(tools.tool_schema()) & ARCHIVE


@pytest.mark.parametrize("name", sorted(ARCHIVE))
def test_archive_tool_denied_without_access(monkeypatch, name):
    search, mail = AsyncMock(return_value={"results": [1]}), AsyncMock(return_value={"results": [1]})
    monkeypatch.setattr(tools, "_call_n8n_search", search)
    monkeypatch.setattr(tools, "_call_n8n_mail", mail)
    res = asyncio.run(tools.execute_tool(name, {"query": "Kontoauszug"}, "u", None, archive_access=False))
    assert res["error"] == "access_denied"
    search.assert_not_called()
    mail.assert_not_called()


@pytest.mark.parametrize("name, fake", [
    ("search_documents", "_call_n8n_search"), ("search_images", "_call_n8n_search"),
    ("get_document_details", "_call_n8n_search"), ("search_emails", "_call_n8n_mail"),
])
def test_archive_tool_runs_with_access(monkeypatch, name, fake):
    call = AsyncMock(return_value={"results": ["hit"]})
    monkeypatch.setattr(tools, fake, call)
    res = asyncio.run(tools.execute_tool(name, {"query": "Kontoauszug"}, "u", None, archive_access=True))
    assert res == {"results": ["hit"]}
    call.assert_awaited_once()


def test_home_assistant_unaffected_for_guest(monkeypatch):
    ha = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(tools, "_call_n8n_ha", ha)
    res = asyncio.run(tools.execute_tool("home_assistant", {"command": "Licht an"}, "u", None))
    assert res == {"success": True}


class _Pool:
    def __init__(self, role=None, exc=None):
        self.role, self.exc, self.args = role, exc, None

    async def fetchval(self, sql, *args):
        if self.exc:
            raise self.exc
        self.args = args
        return self.role


@pytest.mark.parametrize("role, expected", [
    ("admin", True), ("haushalt", True), ("guest", False), (None, False),
    ("user", False), ("child", False),  # legacy values never grant access
])
def test_archive_access_by_db_role(monkeypatch, role, expected):
    pool = _Pool(role)
    monkeypatch.setattr(tools.memory, "pool", lambda: pool)
    assert asyncio.run(tools.archive_access("a-uuid")) is expected
    assert pool.args == ("a-uuid",)


def test_archive_access_fails_closed(monkeypatch):
    monkeypatch.setattr(tools.memory, "pool", lambda: _Pool(exc=RuntimeError("db down")))
    assert asyncio.run(tools.archive_access("a-uuid")) is False


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
def test_prompt_with_archive_lists_tools():
    from app import memory
    p = memory.build_system_prompt({"preferences": {"sprache": "en"}}, archive_access=True)
    assert "search_documents" in p and "search_emails" in p
    assert "keinen Zugriff" not in p


def test_prompt_without_archive_declines_in_user_language():
    from app import memory
    p = memory.build_system_prompt({"preferences": {"sprache": "en"}}, archive_access=False)
    assert "search_documents" not in p and "search_emails" not in p
    assert "keinen Zugriff auf Dokumente" in p
    assert "home_assistant" in p
    # the user's language instruction is still part of the prompt
    assert memory._llm_instruction_for("en") in p


# ---------------------------------------------------------------------------
# Streaming passes the decision through
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("access", [True, False])
def test_stream_chat_uses_archive_access(monkeypatch, access):
    from app import streaming
    from tests.test_streaming_calendar import _Exc, _FakeLLMClient, _text_round, _tool_call_round

    monkeypatch.setattr(streaming.httpx, "AsyncClient", _FakeLLMClient, raising=False)
    monkeypatch.setattr(streaming.httpx, "TimeoutException", _Exc, raising=False)
    monkeypatch.setattr(streaming.httpx, "HTTPError", _Exc, raising=False)
    streaming.tools.tool_schema.reset_mock()
    streaming.tools.tool_schema.return_value = [
        {"type": "function", "function": {"name": "search_documents", "parameters": {}}}]
    execute = AsyncMock(return_value={"results": []})
    monkeypatch.setattr(streaming.tools, "execute_tool", execute)
    _FakeLLMClient.rounds = [_tool_call_round("search_documents", {"query": "x"}), _text_round("ok")]
    _FakeLLMClient.payloads = []

    async def collect():
        return [sse async for sse, _ in streaming.stream_chat(
            user_message="x", history=[], system_prompt="s", user_id="u", archive_access=access)]
    asyncio.run(collect())

    streaming.tools.tool_schema.assert_called_with(access)
    assert execute.await_args.kwargs == {"archive_access": access}
