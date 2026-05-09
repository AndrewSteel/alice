"""
Tool execution for the streaming LLM path.

Tools advertised to the LLM:
  - search_documents     → POST N8N_TOOL_SEARCH_URL  {operation: 'search', ...}
  - get_document_details → POST N8N_TOOL_SEARCH_URL  {operation: 'details', ...}
  - home_assistant       → POST N8N_TOOL_HA_URL      (only if URL is set)
  - remember             → direct write to alice.user_profiles
  - recall               → direct read from Weaviate AliceMemory

Each tool returns a dict that is given verbatim back to Ollama as the
tool result. Errors are returned as {"error": "..."} so the LLM can
explain the problem to the user instead of crashing the stream.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from . import memory

logger = logging.getLogger("alice-chat-stream.tools")

N8N_TOOL_SEARCH_URL = os.environ.get("N8N_TOOL_SEARCH_URL", "").strip()
N8N_TOOL_HA_URL = os.environ.get("N8N_TOOL_HA_URL", "").strip()
TOOL_TIMEOUT_SECONDS = float(os.environ.get("TOOL_TIMEOUT_SECONDS", "15"))


# ---------------------------------------------------------------------------
# Tool schema (Ollama function-calling format)
# ---------------------------------------------------------------------------
def tool_schema() -> list[dict]:
    schema: list[dict] = [
        {
            "type": "function",
            "function": {
                "name": "search_documents",
                "description": (
                    "Durchsucht das Dokumentenarchiv (Rechnungen, Kontoauszüge, "
                    "BankTransactions, Verträge, E-Mails, Wertpapierabrechnungen). "
                    "Für Fragen nach konkreten Zahlungen/Buchungen "
                    "doc_type='BankTransaction' verwenden."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Suchbegriff oder Frage auf Deutsch"},
                        "doc_type": {
                            "type": "string",
                            "description": "Rechnung | Kontoauszug | BankTransaction | Dokument | Email | WertpapierAbrechnung | Vertrag | alle",
                        },
                        "date_from": {"type": "string", "description": "YYYY-MM-DD (optional)"},
                        "date_to": {"type": "string", "description": "YYYY-MM-DD (optional)"},
                        "direction": {
                            "type": "string",
                            "description": "Nur BankTransaction: credit (Eingang) | debit (Ausgang). Leer = beide.",
                        },
                        "limit": {"type": "integer", "description": "1-20, Standard 5"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_document_details",
                "description": "Holt alle Details zu einem Dokument anhand weaviate_id + collection.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "weaviate_id": {"type": "string"},
                        "collection": {"type": "string"},
                    },
                    "required": ["weaviate_id", "collection"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remember",
                "description": "Speichert dauerhaft eine Information über den Nutzer (Fakt oder Präferenz).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Kurzer Bezeichner, z.B. 'lieblingsfarbe'"},
                        "value": {"type": "string", "description": "Wert, z.B. 'blau'"},
                    },
                    "required": ["key", "value"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "recall",
                "description": "Sucht semantisch in vergangenen Gesprächen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "description": "Default 5"},
                    },
                    "required": ["query"],
                },
            },
        },
    ]
    if N8N_TOOL_HA_URL:
        schema.append({
            "type": "function",
            "function": {
                "name": "home_assistant",
                "description": (
                    "Steuert Home-Assistant-Geräte. Nur verwenden, wenn der Nutzer "
                    "explizit etwas im Smart Home tun möchte (Licht, Heizung, ...)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Natürlich-sprachlicher Befehl, z.B. 'Wohnzimmerlicht einschalten'",
                        },
                    },
                    "required": ["command"],
                },
            },
        })
    return schema


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------
async def execute_tool(
    name: str,
    args: dict[str, Any],
    user_id: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """
    Run a single tool call. Always returns a dict — never raises.
    """
    try:
        if name == "search_documents":
            return await _call_n8n_search({
                "operation": "search",
                "user_id": user_id,
                "query": str(args.get("query") or "").strip(),
                "doc_type": args.get("doc_type") or "",
                "date_from": args.get("date_from") or "",
                "date_to": args.get("date_to") or "",
                "direction": args.get("direction") or "",
                "limit": int(args.get("limit") or 5),
            }, client)

        if name == "get_document_details":
            return await _call_n8n_search({
                "operation": "details",
                "user_id": user_id,
                "weaviate_id": str(args.get("weaviate_id") or ""),
                "collection": str(args.get("collection") or ""),
            }, client)

        if name == "home_assistant":
            if not N8N_TOOL_HA_URL:
                return {"error": "Home-Assistant-Tool ist nicht konfiguriert."}
            return await _call_n8n_ha({
                "user_id": user_id,
                "command": str(args.get("command") or "").strip(),
            }, client)

        if name == "remember":
            key = str(args.get("key") or "").strip()
            value = args.get("value")
            if not key:
                return {"error": "remember: key ist erforderlich"}
            await memory.upsert_profile_fact(user_id, key, value)
            return {"success": True, "stored": {"key": key}}

        if name == "recall":
            query = str(args.get("query") or "").strip()
            limit = int(args.get("limit") or 5)
            results = await memory.recall_long_term(user_id, query, limit=limit)
            return {"results": results}

        return {"error": f"Unbekanntes Tool: {name}"}

    except httpx.TimeoutException:
        logger.warning("Tool %s timed out", name)
        return {"error": "timeout", "tool": name}
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return {"error": str(exc), "tool": name}


async def _call_n8n_search(payload: dict, client: httpx.AsyncClient) -> dict:
    if not N8N_TOOL_SEARCH_URL:
        return {"error": "alice-tool-search webhook URL nicht konfiguriert"}
    resp = await client.post(
        N8N_TOOL_SEARCH_URL,
        json=payload,
        timeout=TOOL_TIMEOUT_SECONDS,
    )
    return _parse_n8n_response(resp)


async def _call_n8n_ha(payload: dict, client: httpx.AsyncClient) -> dict:
    resp = await client.post(
        N8N_TOOL_HA_URL,
        json=payload,
        timeout=TOOL_TIMEOUT_SECONDS,
    )
    return _parse_n8n_response(resp)


def _parse_n8n_response(resp: httpx.Response) -> dict:
    if resp.status_code >= 500:
        return {"error": f"n8n returned HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except Exception:
        return {"error": "Invalid JSON from n8n", "body": resp.text[:500]}
    # n8n webhook responses can be a list of items or a single object
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {"results": data}
    if isinstance(data, dict):
        return data
    return {"results": data}
