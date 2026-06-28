"""
Ollama streaming generator with tool-use.

Outputs SSE events:
  data: {"type":"token","content":"..."}        — every text chunk
  data: {"type":"thinking","content":"..."}     — reasoning chunk (PROJ-37)
  data: {"type":"tool_start","tool":"...","status":"...","query":"..."}
  data: {"type":"tool_end","tool":"...","ok":true,"summary":"..."}
  data: {"type":"error","message":"..."}
  data: {"type":"done","usage":{...}}
  data: [DONE]

The generator may loop: when Ollama emits a tool_call, we execute it,
append the tool result to the message list, and re-invoke /api/chat.
We cap the number of tool rounds to avoid infinite loops.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator

import httpx

from . import metrics, tools

logger = logging.getLogger("alice-chat-stream.streaming")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "60"))

# PROJ-37: stream Ollama reasoning tokens (message.thinking) to the client.
# Set to "false" / "0" / "no" to disable without a code change.
OLLAMA_THINK = os.environ.get("OLLAMA_THINK", "true").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
    "",
)

MAX_TOOL_ROUNDS = 4

# Hard caps for user-visible tool status and summary strings.
TOOL_STATUS_MAX_LEN = 80
TOOL_SUMMARY_MAX_LEN = 80
TOOL_ERROR_DETAIL_MAX_LEN = 60


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


def _truncate(text: str, max_len: int) -> str:
    """Hard cap with ellipsis (single-char …)."""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    # Reserve one char for the ellipsis.
    return text[: max_len - 1].rstrip() + "…"


def _build_tool_status(tool_name: str, args: dict[str, Any]) -> str:
    """
    Dynamic, user-friendly status text shown while a tool runs.
    Falls back to a generic "Führe {tool} aus…" for unknown tools.
    """
    if tool_name == "search_documents":
        query = str(args.get("query") or "").strip()
        if query:
            return _truncate(f"Suche nach '{query}'…", TOOL_STATUS_MAX_LEN)
        return "Suche in Dokumenten…"

    if tool_name == "get_document_details":
        doc_id = (
            str(args.get("weaviate_id") or "").strip()
            or str(args.get("document_id") or "").strip()
        )
        if doc_id:
            return _truncate(f"Lade Dokument {doc_id}…", TOOL_STATUS_MAX_LEN)
        return "Lade Dokumentdetails…"

    if tool_name == "home_assistant":
        command = str(args.get("command") or "").strip()
        if command:
            return _truncate(f"Smart Home: {command}…", TOOL_STATUS_MAX_LEN)
        return "Steuere Smart Home…"

    if tool_name == "recall":
        query = str(args.get("query") or "").strip()
        if query:
            return _truncate(f"Erinnere mich an '{query}'…", TOOL_STATUS_MAX_LEN)
        return "Suche in Erinnerungen…"

    if tool_name == "remember":
        key = str(args.get("key") or "").strip()
        value_raw = args.get("value")
        value = "" if value_raw is None else str(value_raw).strip()
        fact_raw = str(args.get("fact") or "").strip()
        if key and value:
            return _truncate(f"Merke: {key} = {value}…", TOOL_STATUS_MAX_LEN)
        if fact_raw:
            return _truncate(f"Merke: '{fact_raw}'…", TOOL_STATUS_MAX_LEN)
        return "Merke mir das…"

    return _truncate(f"Führe {tool_name} aus…", TOOL_STATUS_MAX_LEN)


def _result_count(result: dict[str, Any]) -> int | None:
    """Best-effort hit-count extraction from a tool result."""
    for key in ("count", "total", "n", "num_results"):
        v = result.get(key)
        if isinstance(v, int):
            return v
    for key in ("results", "hits", "documents", "items", "memories"):
        v = result.get(key)
        if isinstance(v, list):
            return len(v)
    return None


def _build_tool_summary(tool_name: str, ok: bool, result: dict[str, Any]) -> str:
    """
    Short German summary of the tool outcome, shown after tool_end.
    Returns "" if there's nothing useful to say.
    """
    if not ok:
        err = str(result.get("error") or "").strip()
        if err and err != "timeout":
            return _truncate(
                f"Fehler: {_truncate(err, TOOL_ERROR_DETAIL_MAX_LEN)}",
                TOOL_SUMMARY_MAX_LEN,
            )
        if err == "timeout":
            return "Fehler: Zeitüberschreitung"
        return "Fehler"

    if tool_name == "search_documents":
        n = _result_count(result)
        if n is None or n <= 0:
            return "Keine Dokumente gefunden"
        return f"{n} Dokument{'e' if n != 1 else ''} gefunden"

    if tool_name == "recall":
        n = _result_count(result)
        if n is None or n <= 0:
            return "Keine Erinnerungen gefunden"
        return f"{n} Erinnerung{'en' if n != 1 else ''} gefunden"

    if tool_name == "remember":
        return "Gespeichert"

    if tool_name == "home_assistant":
        return "Ausgeführt"

    if tool_name == "get_document_details":
        return "Geladen"

    return ""


async def stream_chat(
    *,
    user_message: str,
    history: list[dict],
    system_prompt: str,
    user_id: str,
    anrede: str = "du",
) -> AsyncIterator[tuple[bytes, dict]]:
    """
    Yields (sse_bytes, side_effect_dict). side_effect_dict carries data the
    caller (main.py) needs after the stream ends:
        {"final_text": str, "tool_calls": [...], "usage": {...}}
    Only the LAST yield contains a meaningful side_effect.
    """
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    accumulated_text = ""
    thinking_accumulator: list[str] = []
    tool_call_log: list[dict] = []
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
    rounds = 0
    thinking_start_sent = False

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SECONDS) as client:
        while rounds <= MAX_TOOL_ROUNDS:
            rounds += 1
            payload = {
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": True,
                "tools": tools.tool_schema(),
                # PROJ-37: top-level `think` toggles Ollama's reasoning stream.
                # We emit message.thinking chunks as a separate SSE event.
                "think": OLLAMA_THINK,
            }

            pending_tool_calls: list[dict] = []
            assistant_chunk_text = ""
            done_flag = False
            try:
                async with client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                        logger.error("Ollama HTTP %s: %s", resp.status_code, body)
                        yield (_sse({"type": "error", "message": f"Ollama error {resp.status_code}"}), {})
                        return

                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            logger.warning("Ollama non-JSON line: %s", line[:200])
                            continue

                        msg = chunk.get("message") or {}
                        # PROJ-37: emit thinking BEFORE content (Ollama orders them this way).
                        # Thinking tokens are NEVER added to accumulated_text and NEVER counted
                        # in chat_tokens_total — they are flushed to the client and forgotten.
                        thinking = msg.get("thinking") or ""
                        if thinking:
                            thinking_accumulator.append(thinking)
                            if not thinking_start_sent:
                                thinking_start_sent = True
                                yield (_sse({"type": "thinking_start", "anrede": anrede}), {})
                            yield (_sse({"type": "thinking", "content": thinking}), {})

                        content = msg.get("content") or ""
                        if content:
                            assistant_chunk_text += content
                            accumulated_text += content
                            metrics.CHAT_TOKENS_TOTAL.inc()
                            yield (_sse({"type": "token", "content": content}), {})

                        # Ollama may emit tool_calls inside the streaming chunks
                        tcs = msg.get("tool_calls")
                        if tcs:
                            for tc in tcs:
                                pending_tool_calls.append(tc)

                        if chunk.get("done"):
                            done_flag = True
                            usage["prompt_tokens"] += int(chunk.get("prompt_eval_count") or 0)
                            usage["completion_tokens"] += int(chunk.get("eval_count") or 0)
                            break

            except httpx.TimeoutException:
                logger.warning("Ollama stream timed out after %ss", OLLAMA_TIMEOUT_SECONDS)
                yield (_sse({"type": "error", "message": "Zeitüberschreitung beim LLM."}), {})
                return
            except httpx.HTTPError as exc:
                logger.error("Ollama HTTP error: %s", exc)
                yield (_sse({"type": "error", "message": "Verbindungsfehler zum LLM."}), {})
                return

            # No tool calls → final answer
            if not pending_tool_calls:
                # Append the assistant's full message to history (not strictly needed since
                # we exit the loop, but keeps semantics clean if extended later).
                if assistant_chunk_text:
                    messages.append({"role": "assistant", "content": assistant_chunk_text})
                break

            # Tool calls present — keep the partial assistant message + tool_calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": assistant_chunk_text,
                "tool_calls": pending_tool_calls,
            }
            messages.append(assistant_msg)

            # Execute each tool, emit start/end events, append results
            for tc in pending_tool_calls:
                fn = (tc.get("function") or {})
                tool_name = fn.get("name") or "unknown"
                raw_args = fn.get("arguments")
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}

                # PROJ-37: dynamic status text built from the tool arguments.
                status_text = _build_tool_status(tool_name, args)
                query_hint = args.get("query") or args.get("command") or ""
                yield (_sse({
                    "type": "tool_start",
                    "tool": tool_name,
                    "status": status_text,
                    "query": query_hint,
                }), {})

                result = await tools.execute_tool(tool_name, args, user_id, client)
                ok = "error" not in result
                outcome = (
                    "timeout" if result.get("error") == "timeout"
                    else ("success" if ok else "error")
                )
                metrics.TOOL_CALLS_TOTAL.labels(tool=tool_name, outcome=outcome).inc()

                tool_call_log.append({
                    "tool": tool_name,
                    "arguments": args,
                    "ok": ok,
                    "result_preview": _preview(result),
                })

                # Strip internal debug/metadata keys before the LLM sees the
                # result — these contain raw Weaviate responses that the model
                # would otherwise count/summarise, causing discrepancies with
                # the filtered `results` array (PROJ-54 bug #2).
                _LLM_STRIP_KEYS = {"_debug", "_meta", "_raw"}
                result_for_llm = {k: v for k, v in result.items() if k not in _LLM_STRIP_KEYS}

                # Pass the result back to Ollama
                tool_msg: dict[str, Any] = {
                    "role": "tool",
                    "name": tool_name,
                    "content": json.dumps(result_for_llm, ensure_ascii=False),
                }
                tc_id = tc.get("id")
                if tc_id:
                    tool_msg["tool_call_id"] = tc_id
                messages.append(tool_msg)

                # PROJ-37: short German outcome summary in the tool_end event.
                end_evt: dict[str, Any] = {
                    "type": "tool_end",
                    "tool": tool_name,
                    "ok": ok,
                }
                summary = _build_tool_summary(tool_name, ok, result)
                if summary:
                    end_evt["summary"] = summary
                yield (_sse(end_evt), {})

                # PROJ-54: emit vision_results when tool returns docs with weaviate_uuid.
                vision_items = _extract_vision_results(result)
                if vision_items:
                    yield (_sse({"type": "vision_results", "results": vision_items}), {})

            if not done_flag:
                # Some Ollama versions don't set done=true on the chunk that contains
                # tool_calls; loop again to let the model finish its turn.
                continue

            # done was true alongside tool_calls — still loop so the model can
            # produce its final answer using the tool result.
            continue

        # End of while loop — emit the done event with side-effect payload
        side = {
            "final_text": accumulated_text,
            "thinking_text": "".join(thinking_accumulator),
            "tool_calls": tool_call_log,
            "usage": usage,
        }
        # Signal conversation end for HA commands. The Wyoming voice path uses
        # this to close the session immediately after the TTS confirmation plays,
        # rather than waiting 6 s for the silence-detection turn.
        if any(tc.get("tool") == "home_assistant" for tc in tool_call_log):
            yield (_sse({"type": "conversation_end"}), {})
        yield (_sse({"type": "done", "usage": usage}), side)
        yield (b"data: [DONE]\n\n", {})


def _extract_vision_results(result: dict[str, Any]) -> list[dict] | None:
    """
    PROJ-54: detect if a tool result contains documents with weaviate_uuid/weaviate_id.
    alice-tool-search returns items with weaviate_id + collection fields.
    Returns a list of VisionResult dicts, or None if no vision results found.
    """
    candidates: list[Any] = []
    for key in ("results", "hits", "documents", "items"):
        v = result.get(key)
        if isinstance(v, list) and v:
            candidates = v
            break

    if not candidates:
        return None

    vision: list[dict] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        # alice-tool-search uses weaviate_id; fallback to weaviate_uuid for other tools
        uuid = (
            item.get("weaviate_id")
            or item.get("weaviate_uuid")
            or (item.get("_additional") or {}).get("id")
        )
        if not uuid:
            continue

        # alice-tool-search uses collection; other tools may use document_type / doc_type
        doc_type = str(
            item.get("collection")
            or item.get("document_type")
            or item.get("doc_type")
            or "Document"
        )

        # alice-tool-search uses title_or_summary for summary text
        summary = (
            item.get("title_or_summary")
            or item.get("summary")
            or item.get("ai_summary")
            or None
        )

        # Build metadata from known fields; key_fields dict flattened if present
        meta: dict[str, Any] = {}
        for k in ("date", "amount", "sender", "iban", "subject",
                  "invoiceDate", "totalAmount", "amountGross", "issuer",
                  "statementDate", "bankName", "accountIban",
                  "transactionDate", "counterparty", "direction",
                  "sentAt", "fromAddress", "emailSubject",
                  "score"):
            if item.get(k) is not None:
                meta[k] = item[k]
        # Flatten key_fields dict from alice-tool-search results
        key_fields = item.get("key_fields")
        if isinstance(key_fields, dict):
            for k, v in key_fields.items():
                if v is not None:
                    meta.setdefault(k, v)

        # filename: not directly in tool results; derive from key_fields or leave empty
        filename = str(
            item.get("filename")
            or item.get("fileName")
            or item.get("file_path")
            or item.get("title")
            or ""
        )

        vision.append({
            "uuid": str(uuid),
            "document_type": doc_type,
            "filename": filename,
            "metadata": meta,
            "summary": str(summary) if summary else None,
        })

    return vision if vision else None


def _preview(value: Any, maxlen: int = 300) -> Any:
    """Compact preview suitable for storing in alice.messages.tool_results."""
    try:
        s = json.dumps(value, ensure_ascii=False)
    except Exception:
        s = str(value)
    return s[:maxlen]
