"""
Ollama streaming generator with tool-use.

Outputs SSE events:
  data: {"type":"token","content":"..."}        — every text chunk
  data: {"type":"tool_start","tool":"...","status":"..."}
  data: {"type":"tool_end","tool":"...","ok":true}
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

MAX_TOOL_ROUNDS = 4

# Friendly status text shown to the user while a tool runs
TOOL_STATUS_TEXT = {
    "search_documents": "Suche in Dokumenten…",
    "get_document_details": "Lade Dokumentdetails…",
    "home_assistant": "Steuere Smart Home…",
    "recall": "Suche in Erinnerungen…",
    "remember": "Merke mir das…",
}


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


async def stream_chat(
    *,
    user_message: str,
    history: list[dict],
    system_prompt: str,
    user_id: str,
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
    tool_call_log: list[dict] = []
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
    rounds = 0

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SECONDS) as client:
        while rounds <= MAX_TOOL_ROUNDS:
            rounds += 1
            payload = {
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": True,
                "tools": tools.tool_schema(),
                "options": {"think": False},
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

                status_text = TOOL_STATUS_TEXT.get(tool_name, f"Führe {tool_name} aus…")
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

                # Pass the result back to Ollama
                tool_msg: dict[str, Any] = {
                    "role": "tool",
                    "name": tool_name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
                tc_id = tc.get("id")
                if tc_id:
                    tool_msg["tool_call_id"] = tc_id
                messages.append(tool_msg)

                yield (_sse({
                    "type": "tool_end",
                    "tool": tool_name,
                    "ok": ok,
                }), {})

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
            "tool_calls": tool_call_log,
            "usage": usage,
        }
        yield (_sse({"type": "done", "usage": usage}), side)
        yield (b"data: [DONE]\n\n", {})


def _preview(value: Any, maxlen: int = 300) -> Any:
    """Compact preview suitable for storing in alice.messages.tool_results."""
    try:
        s = json.dumps(value, ensure_ascii=False)
    except Exception:
        s = str(value)
    return s[:maxlen]
