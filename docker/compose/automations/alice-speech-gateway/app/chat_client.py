"""
Chat client — consumes the alice-chat-stream SSE endpoint.

alice-chat-stream owns conversation history; the gateway is stateless and
just forwards `session_id` + user transcript and yields back text tokens.

SSE event shapes produced by alice-chat-stream (see streaming.py):
  data: {"type":"token","content":"..."}
  data: {"type":"thinking_start","anrede":"..."}  — first thinking token, triggers waiting message
  data: {"type":"thinking","content":"..."}        — reasoning, NOT spoken
  data: {"type":"tool_start"|"tool_end", ...}      — ignored for TTS
  data: {"type":"error","message":"..."}
  data: {"type":"done","usage":{...}}
  data: {"type":"conversation_end"}                — ends continued conversation
  data: [DONE]
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx
from httpx_sse import aconnect_sse

from . import config

logger = logging.getLogger("alice-speech-gateway.chat_client")


class ChatError(Exception):
    """Raised when alice-chat-stream is unreachable or returns an error."""


class ChatTimeout(ChatError):
    """Raised when the AI response exceeds AI_TIMEOUT_SECONDS."""


class ChatEvent:
    """A single decoded event from the AI token stream."""

    __slots__ = ("kind", "text")

    def __init__(self, kind: str, text: str = "") -> None:
        # kind: "token" | "conversation_end" | "error" | "done"
        self.kind = kind
        self.text = text


async def stream_reply(
    session_id: str,
    user_id: str,
    transcript: str,
    jwt_token: str,
    device_id: str | None = None,
) -> AsyncIterator[ChatEvent]:
    """
    POST the transcript to alice-chat-stream and yield ChatEvents.

    `thinking` chunks and tool events are dropped — only spoken-text tokens,
    conversation_end and errors are surfaced. The caller is responsible for
    cancelling this generator on barge-in (asyncio task cancellation).
    """
    url = f"{config.CHAT_STREAM_URL}/stream/chat"
    headers = {"Authorization": f"Bearer {jwt_token}"}
    source = f"esphome:{device_id}" if device_id else "esphome"
    payload = {"session_id": session_id, "content": transcript, "source": source}
    timeout = httpx.Timeout(config.AI_TIMEOUT_SECONDS, read=config.AI_TIMEOUT_SECONDS)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with aconnect_sse(
                client, "POST", url, json=payload, headers=headers
            ) as event_source:
                if event_source.response.status_code != 200:
                    raise ChatError(
                        f"chat-stream returned {event_source.response.status_code}"
                    )
                async for sse in event_source.aiter_sse():
                    if sse.data == "[DONE]":
                        yield ChatEvent("done")
                        return
                    try:
                        event = json.loads(sse.data)
                    except json.JSONDecodeError:
                        continue
                    etype = event.get("type")
                    if etype == "token":
                        yield ChatEvent("token", event.get("content", ""))
                    elif etype == "thinking_start":
                        yield ChatEvent("thinking_start", event.get("anrede", "du"))
                    elif etype == "conversation_end":
                        yield ChatEvent("conversation_end")
                    elif etype == "error":
                        raise ChatError(event.get("message", "AI-Fehler"))
                    # thinking / tool_start / tool_end are intentionally ignored
    except httpx.TimeoutException as exc:
        logger.warning("AI response timed out after %ss", config.AI_TIMEOUT_SECONDS)
        raise ChatTimeout("AI-Timeout") from exc
    except httpx.HTTPError as exc:
        logger.error("chat-stream connection error: %s", exc)
        raise ChatError("AI nicht erreichbar") from exc
