"""alice-llm-gateway — priority gateway in front of llama-3090 (PROJ-111).

Endpoints:
  POST /v1/chat/completions  queued for the single llama-3090 slot (interactive first)
  GET  /v1/models            forwarded directly (router metadata, no GPU slot)
  GET  /health               gateway liveness + upstream reachability
  GET  /metrics              Prometheus

Every other path is 404 — the gateway is not an open proxy onto llama.cpp.
Request and response bodies are passed through unchanged (streamed, no
buffering), so token streaming, reasoning tokens and tool calls behave exactly
as with a direct call. The caller's own key is swapped for the llama-3090 key.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager, suppress

import httpx
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import config, metrics
from .scheduler import TIERS, SlotScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("alice-llm-gateway")

# (method, path) -> needs the GPU slot
PROXY_ROUTES = {
    ("POST", "/v1/chat/completions"): True,
    ("GET", "/v1/models"): False,
}

# Hop-by-hop / rewritten headers that must not be copied across the proxy.
_DROP_REQUEST_HEADERS = {
    b"host", b"authorization", b"content-length", b"connection", b"keep-alive",
    b"transfer-encoding", b"te", b"trailer", b"upgrade", b"proxy-authorization",
    b"proxy-connection",
}
_DROP_RESPONSE_HEADERS = {
    b"connection", b"keep-alive", b"transfer-encoding", b"te", b"trailer", b"upgrade",
    b"proxy-connection",
}


class _State:
    clients: list[config.Client]
    upstream_key: str
    http: httpx.AsyncClient
    scheduler: SlotScheduler


state = _State()


class BodyTooLarge(Exception):
    pass


class ClientGone(Exception):
    pass


# ---------------------------------------------------------------------------
# ASGI helpers
# ---------------------------------------------------------------------------
def _bearer(scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            if scheme.lower() == "bearer" and token.strip():
                return token.strip()
            return None
    return None


async def _send_json(send, status: int, message: str, err_type: str) -> None:
    # OpenAI-style error body, same shape llama.cpp returns.
    body = json.dumps({"error": {"code": status, "message": message, "type": err_type}}).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _read_body(receive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise ClientGone
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > config.MAX_BODY_BYTES:
            raise BodyTooLarge
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks)


async def _wait_disconnect(receive) -> None:
    """Resolves once the caller has gone (body is already fully read)."""
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return


# ---------------------------------------------------------------------------
# Proxy
# ---------------------------------------------------------------------------
async def _forward(scope, send, body: bytes) -> tuple[str, int | None]:
    """Forward to llama-3090 and stream the answer back. Returns (outcome, status)."""
    headers = [(k, v) for k, v in scope["headers"] if k.lower() not in _DROP_REQUEST_HEADERS]
    headers.append((b"authorization", f"Bearer {state.upstream_key}".encode()))
    url = config.UPSTREAM_URL + scope["path"]
    if scope.get("query_string"):
        url += "?" + scope["query_string"].decode("latin-1")
    request = state.http.build_request(scope["method"], url, headers=headers, content=body)

    try:
        response = await state.http.send(request, stream=True)
    except httpx.TimeoutException:
        await _send_json(send, 504, "LLM upstream timed out", "upstream_timeout")
        return "timeout", 504
    except httpx.HTTPError as exc:
        logger.warning("upstream unreachable: %s", exc)
        await _send_json(send, 502, "LLM upstream unreachable", "upstream_unavailable")
        return "error", 502

    try:
        await send({
            "type": "http.response.start",
            "status": response.status_code,
            "headers": [
                (k, v) for k, v in response.headers.raw if k.lower() not in _DROP_RESPONSE_HEADERS
            ],
        })
        async for chunk in response.aiter_raw():
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})
    except httpx.TimeoutException:
        # Headers are out — leave the response incomplete so the caller sees a
        # broken stream instead of a silently truncated "successful" one.
        return "timeout", response.status_code
    except httpx.HTTPError as exc:
        logger.warning("upstream stream broke: %s", exc)
        return "error", response.status_code
    finally:
        await response.aclose()
    return ("ok" if response.status_code < 400 else "error"), response.status_code


async def proxy(scope, receive, send, uses_slot: bool) -> None:
    path = scope["path"]
    token = _bearer(scope)
    client = config.find_client(state.clients, token) if token else None
    if client is None:
        metrics.REJECTED_TOTAL.labels("unauthorized").inc()
        logger.warning(json.dumps({"event": "llm_request_rejected", "reason": "unauthorized", "path": path}))
        await _send_json(send, 401, "Invalid API Key", "authentication_error")
        return

    try:
        body = await _read_body(receive)
    except ClientGone:
        return
    except BodyTooLarge:
        metrics.REJECTED_TOTAL.labels("too_large").inc()
        await _send_json(send, 413, "Request body too large", "invalid_request_error")
        return

    tier = client.tier
    t_enqueue = time.monotonic()
    wait_s = 0.0
    upstream_s = 0.0
    status: int | None = None
    outcome = "error"  # overwritten on every regular path
    holds_slot = False
    disconnected = asyncio.create_task(_wait_disconnect(receive))
    try:
        if uses_slot:
            acquire = asyncio.create_task(state.scheduler.acquire(tier))
            done, _ = await asyncio.wait({acquire, disconnected}, return_when=asyncio.FIRST_COMPLETED)
            if acquire not in done:
                acquire.cancel()
                try:
                    await acquire
                except asyncio.CancelledError:
                    pass  # removed from the queue, never forwarded
                else:
                    state.scheduler.release()  # granted in the same tick — hand it on
                outcome = "client_abort"
                wait_s = time.monotonic() - t_enqueue
                return
            holds_slot = True
            wait_s = time.monotonic() - t_enqueue

        t_start = time.monotonic()
        forward = asyncio.create_task(_forward(scope, send, body))
        done, _ = await asyncio.wait({forward, disconnected}, return_when=asyncio.FIRST_COMPLETED)
        if forward in done:
            outcome, status = forward.result()
        else:
            forward.cancel()  # closes the upstream connection -> llama stops generating
            with suppress(asyncio.CancelledError):
                await forward
            outcome = "client_abort"
        upstream_s = time.monotonic() - t_start
    finally:
        if holds_slot:
            state.scheduler.release()
        disconnected.cancel()
        if uses_slot:
            metrics.QUEUE_WAIT_SECONDS.labels(tier).observe(wait_s)
            metrics.UPSTREAM_SECONDS.labels(tier).observe(upstream_s)
            metrics.REQUESTS_TOTAL.labels(tier, outcome).inc()
        logger.info(json.dumps({
            "event": "llm_request",
            "caller": client.name,
            "tier": tier,
            "path": path,
            "queued": uses_slot,
            "wait_ms": round(wait_s * 1000),
            "upstream_ms": round(upstream_s * 1000),
            "outcome": outcome,
            "status": status,
        }))


# ---------------------------------------------------------------------------
# Plain routes + lifespan
# ---------------------------------------------------------------------------
async def health(request):
    upstream_ok = False
    try:
        r = await state.http.get(f"{config.UPSTREAM_URL}/health", timeout=2.0)
        upstream_ok = r.status_code == 200
    except httpx.HTTPError:
        pass
    return JSONResponse({
        "status": "ok",
        "upstream": upstream_ok,
        "slot_busy": state.scheduler.busy,
        "queue": {t: state.scheduler.queue_length(t) for t in TIERS},
    })


async def get_metrics(request):
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@asynccontextmanager
async def lifespan(_app):
    state.clients = config.parse_clients(config.read_secret(config.CLIENTS_FILE))
    state.upstream_key = config.read_secret(config.UPSTREAM_KEY_FILE)
    state.scheduler = SlotScheduler()
    state.http = httpx.AsyncClient(timeout=httpx.Timeout(
        connect=config.UPSTREAM_CONNECT_TIMEOUT,
        read=config.UPSTREAM_READ_TIMEOUT,
        write=60.0,
        pool=None,
    ))
    for tier in TIERS:
        metrics.QUEUE_LENGTH.labels(tier).set_function(lambda t=tier: state.scheduler.queue_length(t))
    metrics.SLOT_BUSY.set_function(lambda: 1 if state.scheduler.busy else 0)
    logger.info(
        "gateway ready: upstream=%s callers=%s",
        config.UPSTREAM_URL,
        ", ".join(f"{c.name}({c.tier})" for c in state.clients),
    )
    try:
        yield
    finally:
        await state.http.aclose()


_routes = Starlette(
    routes=[Route("/health", health), Route("/metrics", get_metrics)],
    lifespan=lifespan,
)


async def app(scope, receive, send):
    if scope["type"] == "http":
        uses_slot = PROXY_ROUTES.get((scope["method"], scope["path"]))
        if uses_slot is not None:
            await proxy(scope, receive, send, uses_slot)
            return
    await _routes(scope, receive, send)
