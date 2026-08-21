"""
Admin dashboard data sources (PROJ-77, PROJ-80): Weaviate schema overview,
n8n execution monitoring, and DMS pipeline coverage. Read-only — callers in
main.py gate every endpoint behind `_require_admin`. The n8n API key never
leaves this service.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
import redis.asyncio as redis

from . import memory

logger = logging.getLogger("alice-chat-stream.admin_dashboard")

WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "http://weaviate:8080").rstrip("/")
# Internal docker-network URL, used for server-side calls to n8n's REST API.
N8N_API_URL = os.environ.get("N8N_API_URL", "http://n8n:5678").rstrip("/")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
# Public URL, used only to build links the browser opens in a new tab.
N8N_PUBLIC_URL = os.environ.get("N8N_PUBLIC_URL", "https://n8n.happy-mining.de").rstrip("/")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD") or None

EXECUTION_DISPLAY_LIMIT = 10
EXECUTION_PAGE_SIZE = 50
EXECUTION_MAX_PAGES = 10  # safety cap on pagination while scanning the 7-day window
FAILED_WINDOW_DAYS = 7
HTTP_TIMEOUT_SECONDS = 10.0
DMS_PATH_TO_HASH_KEY = "alice:dms:path_to_hash"
# Used both as the coverage fetch-all cap and the drilldown row cap. The
# total DMS corpus is ~500-2000 objects across ALL seven collections
# combined (see PROJ-78 spec), so 5000 per single collection is a large
# safety margin, not a real ceiling in normal operation.
DRILLDOWN_LIMIT = 5000

# The six LLM-classified DMS types (PROJ-78/79 fields apply to all of them).
# filePath/fileName are camelCase in these six schemas.
DMS_TYPES = ["Invoice", "BankStatement", "Document", "Email", "Contract", "SecuritySettlement"]
# Image is scanned/thumbnailed like the six DMS types but not LLM-classified
# (no classificationUncertain/languageUncertain) and is the only collection
# with geo fields. file_path/file_name are snake_case in this schema.
IMAGE_TYPE = "Image"


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


# ---------------------------------------------------------------------------
# DMS coverage matrix + quality warnings (PROJ-80)
# ---------------------------------------------------------------------------
def _path_field(doc_type: str) -> str:
    return "file_path" if doc_type == IMAGE_TYPE else "filePath"


def _name_field(doc_type: str) -> str | None:
    # Image has no dedicated file-name property — the drilldown derives it
    # from file_path instead (see _shape_drilldown_row).
    return None if doc_type == IMAGE_TYPE else "fileName"


class RedisUnavailableError(Exception):
    """Redis unreachable — path-scan column shows an error state, everything
    else (Weaviate-only) stays usable (PROJ-80 edge case)."""


async def _read_path_scan_counts() -> dict[str, int]:
    """
    Reads the full alice:dms:path_to_hash hash and buckets each path by the
    longest-matching enabled watched-folder prefix. Paths under a folder with
    suggested_type=NULL ("Auto") or under no configured folder at all only
    count toward "total", not toward a specific type — the type is unknown
    until classification runs.

    Returns {"total": n, "Invoice": n, ..., "Image": n} — missing/zero types
    are simply absent from the dict (caller treats missing as 0).
    """
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=HTTP_TIMEOUT_SECONDS,
        socket_timeout=HTTP_TIMEOUT_SECONDS,
    )
    try:
        paths = await client.hkeys(DMS_PATH_TO_HASH_KEY)
    except Exception as exc:
        raise RedisUnavailableError(f"Redis nicht erreichbar: {exc}") from exc
    finally:
        await client.aclose()

    folders = await memory.pool().fetch(
        """
        SELECT path, suggested_type
        FROM alice.dms_watched_folders
        WHERE enabled = true
        ORDER BY length(path) DESC
        """
    )

    counts: dict[str, int] = {"total": len(paths)}
    for p in paths:
        matched_type = None
        for f in folders:
            if p.startswith(f["path"]):
                matched_type = f["suggested_type"]
                break
        if matched_type:
            counts[matched_type] = counts.get(matched_type, 0) + 1
    return counts


def _coverage_pct(scanned: int, actual: int) -> float | None:
    """None means no-data (neutral/grey cell) — 0 scanned and 0 actual."""
    if scanned <= 0 and actual <= 0:
        return None
    if scanned <= 0:
        return 100.0  # nothing to scan against but objects exist — not a gap
    pct = (actual / scanned) * 100.0
    return min(pct, 100.0)  # cap at 100% — scanned < actual is not a gap (edge case)


def _traffic_light(pct: float | None) -> str:
    if pct is None:
        return "neutral"
    if pct >= 100.0:
        return "green"
    if pct >= 95.0:
        return "yellow"
    return "red"


async def _fetch_all_objects(client: httpx.AsyncClient, doc_type: str, fields: str) -> list[dict]:
    """
    Fetches every object of a collection with the given fields, unfiltered.

    Weaviate's `where: IsNull` filter requires per-property null-state
    indexing that isn't enabled on these schemas — confirmed broken live
    during PROJ-73 (silently returns 0 results instead of erroring). To stay
    correct we never filter on "field is/isn't set" or "flag = true" via
    `where`; instead we fetch the full (bounded, ~500-2000 docs total across
    all collections) object set once per collection and filter in Python.
    """
    gql = f"{{ Get {{ {doc_type}(limit: {DRILLDOWN_LIMIT}) {{ {fields} }} }} }}"
    try:
        resp = await client.post(
            f"{WEAVIATE_URL}/v1/graphql",
            json={"query": gql},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise UpstreamError(f"Weaviate-Query fehlgeschlagen ({doc_type}): {body['errors']}")
        return ((body.get("data") or {}).get("Get") or {}).get(doc_type) or []
    except UpstreamError:
        raise
    except Exception as exc:
        raise UpstreamError(f"Weaviate nicht erreichbar: {exc}") from exc


def _coverage_fields(doc_type: str) -> str:
    parts = [_path_field(doc_type), "thumbnail_path"]
    name_field = _name_field(doc_type)
    if name_field:
        parts.append(name_field)
    if doc_type == IMAGE_TYPE:
        parts.append("latitude")
    else:
        parts += ["classificationUncertain", "languageUncertain"]
    return " ".join(parts)


async def get_dms_coverage() -> dict:
    """
    Coverage matrix: path-scan vs Weaviate, thumbnail, and (Image-only) geo
    coverage, per DMS type and totals. Redis failure degrades only the
    path-scan column (AC); Weaviate failure fails the whole tile.
    """
    all_types = DMS_TYPES + [IMAGE_TYPE]

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        objects_by_type = {
            t: await _fetch_all_objects(client, t, _coverage_fields(t)) for t in all_types
        }

    try:
        path_scan = await _read_path_scan_counts()
        redis_error = None
    except RedisUnavailableError as exc:
        path_scan = {}
        redis_error = str(exc)

    rows = []
    total_scanned = 0
    total_weaviate = 0
    total_thumb = 0
    for t in all_types:
        objects = objects_by_type[t]
        weaviate_count = len(objects)
        thumb_count = sum(1 for o in objects if o.get("thumbnail_path"))
        scanned_count = path_scan.get(t, 0) if redis_error is None else None

        total_weaviate += weaviate_count
        total_thumb += thumb_count
        if scanned_count is not None:
            total_scanned += scanned_count

        row = {
            "docType": t,
            "pathScanCount": scanned_count,
            "weaviateCount": weaviate_count,
            "pathScanCoveragePct": (
                None if redis_error else _coverage_pct(scanned_count, weaviate_count)
            ),
            "pathScanStatus": (
                "error" if redis_error else _traffic_light(_coverage_pct(scanned_count, weaviate_count))
            ),
            "thumbnailCoveragePct": _coverage_pct(weaviate_count, thumb_count),
            "thumbnailStatus": _traffic_light(_coverage_pct(weaviate_count, thumb_count)),
        }
        if t == IMAGE_TYPE:
            geo_count = sum(1 for o in objects if o.get("latitude") is not None)
            row["geoCoveragePct"] = _coverage_pct(weaviate_count, geo_count)
            row["geoStatus"] = _traffic_light(_coverage_pct(weaviate_count, geo_count))
        else:
            row["geoCoveragePct"] = None
            row["geoStatus"] = "n/a"
        rows.append(row)

    total_scanned_val = None if redis_error else path_scan.get("total", total_scanned)
    totals = {
        "docType": "total",
        "pathScanCount": total_scanned_val,
        "weaviateCount": total_weaviate,
        "pathScanCoveragePct": None if redis_error else _coverage_pct(total_scanned_val, total_weaviate),
        "pathScanStatus": (
            "error" if redis_error else _traffic_light(_coverage_pct(total_scanned_val, total_weaviate))
        ),
        "thumbnailCoveragePct": _coverage_pct(total_weaviate, total_thumb),
        "thumbnailStatus": _traffic_light(_coverage_pct(total_weaviate, total_thumb)),
        "geoCoveragePct": None,
        "geoStatus": "n/a",
    }

    return {
        "rows": rows,
        "totals": totals,
        "redisError": redis_error,
    }


def _shape_drilldown_row(doc_type: str, obj: dict, reason: str) -> dict:
    path = obj.get(_path_field(doc_type)) or ""
    name_field = _name_field(doc_type)
    file_name = obj.get(name_field) if name_field else (path.rsplit("/", 1)[-1] if path else "")
    return {"fileName": file_name or "", "filePath": path, "reason": reason}


_DRILLDOWN_DIMENSIONS = {
    "thumbnail": "missing_thumbnail",
    "geo": "missing_geo",
    "classificationUncertain": "classification_uncertain",
    "languageUncertain": "language_uncertain",
}


def _drilldown_matches(dimension: str, obj: dict) -> bool:
    if dimension == "thumbnail":
        return not obj.get("thumbnail_path")
    if dimension == "geo":
        return obj.get("latitude") is None
    if dimension == "classificationUncertain":
        return obj.get("classificationUncertain") is True
    if dimension == "languageUncertain":
        return obj.get("languageUncertain") is True
    raise ValueError(f"Unbekannte Dimension: {dimension}")


async def get_dms_drilldown(doc_type: str, dimension: str) -> list[dict]:
    """
    Returns the documents responsible for a coverage gap or quality
    warning: dimension is one of "thumbnail" (missing thumbnail_path),
    "geo" (missing latitude, Image only), "classificationUncertain",
    "languageUncertain" (flag = true). Filtered in Python — see
    _fetch_all_objects for why we don't use Weaviate's `where` here.
    """
    all_types = DMS_TYPES + [IMAGE_TYPE]
    if doc_type not in all_types:
        raise ValueError(f"Unbekannter Dokumenttyp: {doc_type}")
    if dimension not in _DRILLDOWN_DIMENSIONS:
        raise ValueError(f"Unbekannte Dimension: {dimension}")
    if dimension == "geo" and doc_type != IMAGE_TYPE:
        raise ValueError("Dimension 'geo' gilt nur für Image")
    if dimension in ("classificationUncertain", "languageUncertain") and doc_type == IMAGE_TYPE:
        raise ValueError(f"Dimension '{dimension}' gilt nicht für Image")

    reason = _DRILLDOWN_DIMENSIONS[dimension]
    fields = _coverage_fields(doc_type)

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        objects = await _fetch_all_objects(client, doc_type, fields)

    matching = [o for o in objects if _drilldown_matches(dimension, o)]
    return [_shape_drilldown_row(doc_type, obj, reason) for obj in matching]


async def get_dms_quality_warnings() -> dict:
    """
    Counts of classificationUncertain / languageUncertain per DMS type
    and total. Image is excluded — it is not LLM-classified (no such
    fields in its schema). Filtered in Python — see _fetch_all_objects.
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        objects_by_type = {
            t: await _fetch_all_objects(client, t, "classificationUncertain languageUncertain")
            for t in DMS_TYPES
        }

    rows = []
    total_cu = 0
    total_lu = 0
    for t in DMS_TYPES:
        objects = objects_by_type[t]
        cu = sum(1 for o in objects if o.get("classificationUncertain") is True)
        lu = sum(1 for o in objects if o.get("languageUncertain") is True)
        total_cu += cu
        total_lu += lu
        rows.append({"docType": t, "classificationUncertainCount": cu, "languageUncertainCount": lu})

    return {
        "rows": rows,
        "totals": {"docType": "total", "classificationUncertainCount": total_cu, "languageUncertainCount": total_lu},
    }
