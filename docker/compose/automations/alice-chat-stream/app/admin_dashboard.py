"""
Admin dashboard data sources (PROJ-77): Weaviate schema overview and n8n
execution monitoring. Read-only — callers in main.py gate every endpoint
behind `_require_admin`. The n8n API key never leaves this service.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger("alice-chat-stream.admin_dashboard")

WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "http://weaviate:8080").rstrip("/")
# Internal docker-network URL, used for server-side calls to n8n's REST API.
N8N_API_URL = os.environ.get("N8N_API_URL", "http://n8n:5678").rstrip("/")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
# Public URL, used only to build links the browser opens in a new tab.
N8N_PUBLIC_URL = os.environ.get("N8N_PUBLIC_URL", "https://n8n.happy-mining.de").rstrip("/")

EXECUTION_DISPLAY_LIMIT = 10
EXECUTION_PAGE_SIZE = 50
EXECUTION_MAX_PAGES = 10  # safety cap on pagination while scanning the 7-day window
FAILED_WINDOW_DAYS = 7
HTTP_TIMEOUT_SECONDS = 10.0


class UpstreamError(Exception):
    """Weaviate/n8n unreachable or misconfigured — caller maps this to HTTP 502."""


# ---------------------------------------------------------------------------
# Weaviate schema overview (AC-C)
# ---------------------------------------------------------------------------
def _shape_weaviate_schemas(classes: list[str], aggregate: dict) -> list[dict]:
    schemas = []
    for c in classes:
        entries = aggregate.get(c) or []
        count = entries[0]["meta"]["count"] if entries else 0
        schemas.append({"name": c, "count": count})
    return schemas


async def get_weaviate_schemas() -> list[dict]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.get(f"{WEAVIATE_URL}/v1/schema")
            resp.raise_for_status()
            # Weaviate doesn't guarantee a stable order in /v1/schema (it can
            # vary between requests) — sort alphabetically for a deterministic,
            # readable tile (AC-C1).
            classes = sorted(c["class"] for c in (resp.json().get("classes") or []))
        except Exception as exc:
            raise UpstreamError(f"Weaviate nicht erreichbar: {exc}") from exc

        if not classes:
            return []

        aggregate_fields = " ".join(f"{c} {{ meta {{ count }} }}" for c in classes)
        gql = f"{{ Aggregate {{ {aggregate_fields} }} }}"
        try:
            resp = await client.post(
                f"{WEAVIATE_URL}/v1/graphql",
                json={"query": gql},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            aggregate = (resp.json().get("data") or {}).get("Aggregate") or {}
        except Exception as exc:
            raise UpstreamError(f"Weaviate Aggregate-Query fehlgeschlagen: {exc}") from exc

        return _shape_weaviate_schemas(classes, aggregate)


# ---------------------------------------------------------------------------
# n8n execution monitoring (AC-E, AC-F)
# ---------------------------------------------------------------------------
def _execution_url(workflow_id: str, execution_id: str) -> str:
    return f"{N8N_PUBLIC_URL}/workflow/{workflow_id}/executions/{execution_id}"


def _overview_url() -> str:
    return f"{N8N_PUBLIC_URL}/home/executions"


def _shape_running(executions: list[dict], names: dict[str, str]) -> list[dict]:
    return [
        {
            "id": e["id"],
            "workflow_id": e["workflowId"],
            "workflow_name": names.get(e["workflowId"], e["workflowId"]),
            "started_at": e["startedAt"],
            "url": _execution_url(e["workflowId"], e["id"]),
        }
        for e in executions
    ]


def _shape_failed(executions: list[dict], names: dict[str, str]) -> list[dict]:
    return [
        {
            "id": e["id"],
            "workflow_id": e["workflowId"],
            "workflow_name": names.get(e["workflowId"], e["workflowId"]),
            "failed_at": e.get("stoppedAt") or e["startedAt"],
            "url": _execution_url(e["workflowId"], e["id"]),
        }
        for e in executions
    ]


def _split_window(executions: list[dict], cutoff_iso: str) -> tuple[list[dict], bool]:
    """
    executions is one page, newest-first. Returns the entries with
    startedAt >= cutoff_iso, and whether this page crossed the cutoff
    (pagination can stop once it has).
    """
    in_window = []
    reached_end = False
    for e in executions:
        if e.get("startedAt", "") < cutoff_iso:
            reached_end = True
            break
        in_window.append(e)
    return in_window, reached_end


def _require_n8n_config() -> None:
    if not N8N_API_KEY:
        raise UpstreamError("N8N_API_KEY ist nicht konfiguriert")


async def _fetch_executions(
    client: httpx.AsyncClient, status: str, cutoff_iso: str | None
) -> tuple[list[dict], int]:
    """
    Fetch executions with the given status, newest-first, capped at
    EXECUTION_DISPLAY_LIMIT for display. If cutoff_iso is set, only
    executions with startedAt >= cutoff_iso are collected (paginating
    forward until the window ends or EXECUTION_MAX_PAGES is hit — the n8n
    REST API has no date-range filter).

    Returns (executions, extra_count) where extra_count is how many
    additional matching executions exist beyond EXECUTION_DISPLAY_LIMIT
    (bounded by EXECUTION_MAX_PAGES — an admin dashboard has no need to
    paginate through hundreds of executions just to count them exactly).
    """
    headers = {"X-N8N-API-KEY": N8N_API_KEY}
    collected: list[dict] = []
    cursor: str | None = None

    for _ in range(EXECUTION_MAX_PAGES):
        params: dict = {"status": status, "limit": EXECUTION_PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        try:
            resp = await client.get(
                f"{N8N_API_URL}/api/v1/executions", params=params, headers=headers
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise UpstreamError("n8n API-Key ungültig") from exc
            raise UpstreamError(f"n8n nicht erreichbar: {exc}") from exc
        except Exception as exc:
            raise UpstreamError(f"n8n nicht erreichbar: {exc}") from exc

        body = resp.json()
        page = body.get("data") or []

        if cutoff_iso:
            in_window, reached_end = _split_window(page, cutoff_iso)
            collected.extend(in_window)
        else:
            collected.extend(page)
            reached_end = False

        if reached_end or not body.get("nextCursor"):
            break
        cursor = body["nextCursor"]

    extra_count = max(0, len(collected) - EXECUTION_DISPLAY_LIMIT)
    return collected[:EXECUTION_DISPLAY_LIMIT], extra_count


async def _resolve_workflow_names(
    client: httpx.AsyncClient, workflow_ids: set[str]
) -> dict[str, str]:
    headers = {"X-N8N-API-KEY": N8N_API_KEY}
    names: dict[str, str] = {}
    for wf_id in workflow_ids:
        try:
            resp = await client.get(f"{N8N_API_URL}/api/v1/workflows/{wf_id}", headers=headers)
            resp.raise_for_status()
            names[wf_id] = resp.json().get("name", wf_id)
        except Exception as exc:
            logger.warning("Failed to resolve n8n workflow name for %s: %s", wf_id, exc)
            names[wf_id] = wf_id
    return names


async def get_running_executions() -> dict:
    _require_n8n_config()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        executions, extra_count = await _fetch_executions(client, "running", cutoff_iso=None)
        names = await _resolve_workflow_names(client, {e["workflowId"] for e in executions})
    return {
        "executions": _shape_running(executions, names),
        "extra_count": extra_count,
        "overview_url": _overview_url(),
    }


async def get_failed_executions_7d() -> dict:
    _require_n8n_config()
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=FAILED_WINDOW_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        executions, extra_count = await _fetch_executions(client, "error", cutoff_iso=cutoff_iso)
        names = await _resolve_workflow_names(client, {e["workflowId"] for e in executions})
    return {
        "executions": _shape_failed(executions, names),
        "extra_count": extra_count,
        "overview_url": _overview_url(),
    }
