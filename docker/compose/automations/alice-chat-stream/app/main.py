"""
alice-chat-stream — FastAPI service that streams chat responses from Ollama
to the client over Server-Sent Events (SSE).

Endpoints:
  POST /stream/chat          — main streaming chat endpoint (SSE)
  GET  /health
  GET  /metrics              — Prometheus

The service is mounted by nginx under /api/stream/* (PROJ-32).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, field_validator

from . import ha_path, memory, metrics, streaming
from .auth import verify_jwt

# ---------------------------------------------------------------------------
# Logging — structured JSON
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k in ("session_id", "user_id", "latency_ms", "path"):
            v = getattr(record, k, None)
            if v is not None:
                payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_root = logging.getLogger()
_root.handlers.clear()
_handler = logging.StreamHandler()
_handler.setFormatter(_JsonFormatter())
_root.addHandler(_handler)
_root.setLevel(LOG_LEVEL)
logger = logging.getLogger("alice-chat-stream")


# ---------------------------------------------------------------------------
# App + lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await memory.init_pool()
    try:
        yield
    finally:
        await memory.close_pool()


app = FastAPI(title="alice-chat-stream", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    session_id: str = Field(..., description="UUID der Session")
    content: str = Field(..., description="Nutzer-Nachricht")

    @field_validator("session_id")
    @classmethod
    def _check_uuid(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except Exception as exc:
            raise ValueError("session_id muss eine UUID sein") from exc
        return v

    @field_validator("content")
    @classmethod
    def _check_content(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("content darf nicht leer sein")
        if len(v) > 8000:
            raise ValueError("content ist zu lang (max 8000 Zeichen)")
        return v


# ---------------------------------------------------------------------------
# /health and /metrics
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    db_ok = await memory.healthy()
    jwt_ok = bool(os.environ.get("JWT_PUBLIC_KEY_PATH"))
    status = "ok" if (db_ok and jwt_ok) else "degraded"
    return {"status": status, "db": db_ok, "jwt_public_key": jwt_ok}


@app.get("/metrics")
async def get_metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# /stream/chat
# ---------------------------------------------------------------------------
@app.post("/stream/chat")
async def stream_chat_endpoint(
    body: ChatRequest,
    request: Request,
    jwt_payload: dict = Depends(verify_jwt),
):
    """
    Server-Sent Events streaming chat endpoint.

    The user_id comes ONLY from the verified JWT — body.user_id is ignored.
    """
    user_id = jwt_payload["user_id"]
    session_id = body.session_id
    user_message = body.content
    request_start_ms = time.monotonic()

    log_extra = {"session_id": session_id, "user_id": user_id}

    # 1. Persist the user message + load memory BEFORE we open the SSE stream.
    # Failures here must return HTTP 4xx/5xx synchronously, not as SSE errors,
    # so the client knows nothing was streamed.
    try:
        await memory.ensure_session(session_id, user_id)
        await memory.insert_user_message(session_id, user_id, user_message)
        history = await memory.load_working_memory(session_id)
        # The just-inserted user message is included in history; strip its
        # trailing copy so the LLM doesn't see the message twice.
        if history and history[-1]["role"] == "user" and history[-1]["content"] == user_message:
            history = history[:-1]
        profile = await memory.load_user_profile(user_id)
    except Exception as exc:
        logger.error("Memory load failed: %s", exc, extra=log_extra)
        raise HTTPException(status_code=503, detail="Memory unavailable") from exc

    anrede = (profile.get("preferences") or {}).get("anrede", "du")

    # Tier 2: long-term memory — best-effort, never blocks (errors return [])
    long_term = await memory.recall_long_term(user_id, user_message)
    system_prompt = memory.build_system_prompt(profile, long_term_memories=long_term)

    # 2. Stream generator — runs the HA fast-path first, otherwise the LLM stream.
    async def event_generator():
        path_label = "LLM_ONLY"
        final_text = ""
        tool_calls_log: list[dict] = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        try:
            # --- HA Fast-Path ---
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    decision = await ha_path.decide_path(user_message, client)
                    if decision.path == "HA_FAST":
                        path_label = "HA_FAST"
                        text, ha_results = await ha_path.execute_ha_intents(
                            decision.intents, client
                        )
                        # Stream HA result as a single token + done
                        yield f'data: {{"type":"token","content":{json.dumps(text, ensure_ascii=False)}}}\n\n'.encode("utf-8")
                        usage = {"prompt_tokens": 0, "completion_tokens": len(text)}
                        final_text = text
                        tool_calls_log = [{
                            "tool": "home_assistant_fast",
                            "arguments": {"parts": decision.parts},
                            "ok": all(r.get("success") for r in ha_results) if ha_results else True,
                            "result_preview": json.dumps(ha_results, ensure_ascii=False)[:300],
                        }]
                        yield f'data: {{"type":"done","usage":{json.dumps(usage)}}}\n\n'.encode("utf-8")
                        yield b"data: [DONE]\n\n"
                        return
            except Exception as exc:
                logger.warning("HA fast-path errored, falling back to LLM: %s", exc, extra=log_extra)

            # --- LLM streaming ---
            side: dict = {}
            async for sse_bytes, side_effect in streaming.stream_chat(
                user_message=user_message,
                history=history,
                system_prompt=system_prompt,
                user_id=user_id,
                anrede=anrede,
            ):
                # Detect client disconnect — stop iterating gracefully.
                if await request.is_disconnected():
                    logger.info("Client disconnected mid-stream", extra=log_extra)
                    break
                yield sse_bytes
                if side_effect:
                    side = side_effect
            final_text = side.get("final_text", "")
            tool_calls_log = side.get("tool_calls", [])
            usage = side.get("usage", usage)

        except asyncio.CancelledError:
            logger.info("Stream cancelled", extra=log_extra)
            raise
        except Exception as exc:
            logger.error("Stream error: %s", exc, extra=log_extra)
            err_msg = json.dumps({"type": "error", "message": "Interner Fehler beim Streaming."}, ensure_ascii=False)
            yield f"data: {err_msg}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"
            final_text = final_text or "Es ist ein Fehler aufgetreten."
        finally:
            # 3. Persist the assistant message — even if the client disconnected.
            latency_ms = int((time.monotonic() - request_start_ms) * 1000)
            tool_results = {
                "path_taken": path_label,
                "latency_ms": latency_ms,
                "llm_used": path_label != "HA_FAST",
                "usage": usage,
            }
            try:
                await memory.insert_assistant_message(
                    session_id=session_id,
                    user_id=user_id,
                    content=final_text or "",
                    tool_calls=tool_calls_log or None,
                    tool_results=tool_results,
                    token_count=int(usage.get("completion_tokens") or 0),
                )
            except Exception as exc:
                logger.error("Failed to persist assistant message: %s", exc, extra=log_extra)

            metrics.CHAT_REQUESTS_TOTAL.labels(path=path_label).inc()
            metrics.CHAT_LATENCY_SECONDS.labels(path=path_label).observe(latency_ms / 1000.0)
            logger.info(
                "chat completed",
                extra={**log_extra, "latency_ms": latency_ms, "path": path_label},
            )

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # nginx: don't buffer SSE
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )
