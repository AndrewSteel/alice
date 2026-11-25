"""
Read-only queries on the register tables of PROJ-115 (alice.sources, source_stages,
pipeline_stages, source_locations, source_events). One bundled query per view, so a page
over 60,000 sources stays well below one second (AK-46). Nothing here touches the repo or
the NAS.
"""
from __future__ import annotations

from datetime import datetime

KINDS = ("document", "image", "email", "audio", "video")
STATES = ("pending", "running", "done", "failed", "failed_permanent", "skipped")
RETRYABLE = ("failed", "failed_permanent")
ERROR_STATES = ("failed", "failed_permanent", "locked")
LIST_ERROR_CHARS = 300  # error message in lists is shortened; the detail shows it in full
EVENT_LIMIT = 200


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _row(r) -> dict:
    return {k: _iso(v) for k, v in dict(r).items()}


def like_pattern(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ---------------------------------------------------------------- stages + matrix
async def stages(con) -> list[dict]:
    rows = await con.fetch("SELECT name, position, skip_kinds FROM alice.pipeline_stages ORDER BY position, name")
    return [{"name": r["name"], "position": r["position"], "skip_kinds": list(r["skip_kinds"])} for r in rows]


async def matrix(con, kind: str | None, include_deleted: bool) -> dict[str, dict[str, int]]:
    """Number of sources per stage and state (AK-5, AK-6). Deleted sources only on request."""
    rows = await con.fetch(
        """
        SELECT ss.stage, ss.state, count(*) AS n
          FROM alice.source_stages ss
          JOIN alice.sources s ON s.id = ss.source_id
         WHERE ($1::text IS NULL OR s.kind = $1) AND ($2 OR NOT s.deleted)
         GROUP BY ss.stage, ss.state
        """, kind, include_deleted)
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["stage"], {st: 0 for st in STATES})[r["state"]] = r["n"]
    return out


async def counts(con) -> dict:
    """Error numbers for summary and dashboard tile (AK-36), without deleted sources:
    serious = sources with a failed_permanent stage or locked; failed = sources with a stage
    in failed (retry planned)."""
    r = await con.fetchrow(
        """
        WITH f AS (
            SELECT source_id, bool_or(state = 'failed_permanent') AS fp, bool_or(state = 'failed') AS f
              FROM alice.source_stages WHERE state IN ('failed', 'failed_permanent') GROUP BY source_id
        )
        SELECT count(*) FILTER (WHERE NOT s.deleted) AS sources,
               count(*) FILTER (WHERE s.deleted) AS deleted,
               count(*) FILTER (WHERE NOT s.deleted AND s.repo_error IS NOT NULL) AS locked,
               count(*) FILTER (WHERE NOT s.deleted AND f.fp) AS failed_permanent,
               count(*) FILTER (WHERE NOT s.deleted AND (f.fp OR s.repo_error IS NOT NULL)) AS serious,
               count(*) FILTER (WHERE NOT s.deleted AND f.f) AS failed
          FROM alice.sources s LEFT JOIN f ON f.source_id = s.id
        """)
    return {k: int(v or 0) for k, v in dict(r).items()}


# ---------------------------------------------------------------- source list
def _list_where(f: dict, start: int) -> tuple[str, list]:
    """WHERE clause of the source list (stage × filters) with parameters from $start on."""
    conds, args = ["ss.stage = $%d" % start], [f["stage"]]

    def add(cond: str, value):
        args.append(value)
        conds.append(cond % (start + len(args) - 1))

    if f.get("state"):
        add("ss.state = $%d", f["state"])
    if f.get("kind"):
        add("s.kind = $%d", f["kind"])
    deleted = f.get("deleted") or "no"
    if deleted == "no":
        conds.append("NOT s.deleted")
    elif deleted == "yes":
        conds.append("s.deleted")
    locked = f.get("locked") or "all"
    if locked == "yes":
        conds.append("s.repo_error IS NOT NULL")
    elif locked == "no":
        conds.append("s.repo_error IS NULL")
    q = (f.get("q") or "").strip()
    if q:
        args.append(q.lower())
        args.append(like_pattern(q))
        n = start + len(args) - 2
        conds.append(f"(s.id = ${n} OR s.title ILIKE ${n + 1} ESCAPE '\\')")
    return " AND ".join(conds), args


async def source_list(con, f: dict, limit: int, offset: int) -> dict:
    """Sources of one stage, filtered (AK-8–10); the number a bulk retry would hit."""
    where, args = _list_where(f, 1)
    base = f"FROM alice.source_stages ss JOIN alice.sources s ON s.id = ss.source_id WHERE {where}"
    agg = await con.fetchrow(
        f"SELECT count(*) AS total, count(*) FILTER (WHERE ss.state IN ('failed', 'failed_permanent') "
        f"AND NOT s.deleted AND s.repo_error IS NULL) AS retryable {base}", *args)
    n = len(args)
    rows = await con.fetch(
        f"""
        SELECT s.id, s.title, s.kind, s.deleted, s.repo_error IS NOT NULL AS locked, ss.stage, ss.state,
               ss.attempts, left(ss.last_error, {LIST_ERROR_CHARS}) AS error,
               length(ss.last_error) > {LIST_ERROR_CHARS} AS error_truncated,
               ss.last_attempt_at, ss.next_retry_at
          {base}
         ORDER BY ss.last_attempt_at DESC NULLS LAST, s.captured DESC, s.id
         LIMIT ${n + 1} OFFSET ${n + 2}
        """, *args, limit, offset)
    return {"total": agg["total"], "retryable": agg["retryable"], "items": [_row(r) for r in rows]}


async def list_targets(con, f: dict) -> dict[str, list[str]]:
    """Retry targets of a source list selection: source → stages in failed/failed_permanent."""
    where, args = _list_where(f, 1)
    rows = await con.fetch(
        f"SELECT s.id, ss.stage FROM alice.source_stages ss JOIN alice.sources s ON s.id = ss.source_id "
        f"WHERE {where} AND ss.state IN ('failed', 'failed_permanent') AND NOT s.deleted AND s.repo_error IS NULL "
        f"ORDER BY s.id", *args)
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["id"], []).append(r["stage"])
    return out


# ---------------------------------------------------------------- errors
ERRORS_CTE = """
    WITH e AS (
        SELECT s.id, s.title, s.kind, ss.stage, ss.state, ss.attempts, ss.last_error AS error,
               ss.last_attempt_at AS error_at, ss.next_retry_at, ps.position, (s.repo_error IS NOT NULL) AS locked
          FROM alice.source_stages ss
          JOIN alice.sources s ON s.id = ss.source_id
          JOIN alice.pipeline_stages ps ON ps.name = ss.stage
         WHERE ss.state IN ('failed', 'failed_permanent') AND NOT s.deleted
        UNION ALL
        SELECT s.id, s.title, s.kind, NULL, 'locked', NULL, s.repo_error, s.repo_error_at, NULL, -1, TRUE
          FROM alice.sources s
         WHERE s.repo_error IS NOT NULL AND NOT s.deleted
    )
"""
ERRORS_WHERE = ("WHERE ($1::text IS NULL OR e.stage = $1) AND ($2::text IS NULL OR e.state = $2) "
                "AND ($3::text IS NULL OR e.kind = $3)")


async def errors(con, f: dict, limit: int, offset: int) -> dict:
    """Failed stages and locked sources over all stages, newest error first (AK-11)."""
    args = [f.get("stage"), f.get("state"), f.get("kind")]
    agg = await con.fetchrow(
        f"{ERRORS_CTE} SELECT count(*) AS total, count(DISTINCT e.id) FILTER (WHERE e.state <> 'locked' "
        f"AND NOT e.locked) AS retryable FROM e {ERRORS_WHERE}", *args)
    rows = await con.fetch(
        f"""{ERRORS_CTE}
        SELECT e.id, e.title, e.kind, e.stage, e.state, e.attempts, left(e.error, {LIST_ERROR_CHARS}) AS error,
               length(e.error) > {LIST_ERROR_CHARS} AS error_truncated, e.error_at, e.next_retry_at, e.locked
          FROM e {ERRORS_WHERE}
         ORDER BY e.error_at DESC NULLS LAST, e.id, e.position
         LIMIT $4 OFFSET $5
        """, *args, limit, offset)
    return {"total": agg["total"], "retryable": agg["retryable"], "items": [_row(r) for r in rows]}


async def error_targets(con, f: dict) -> dict[str, list[str]]:
    """Retry targets of an error selection: failed stages of sources that are not locked."""
    if f.get("state") == "locked":
        return {}
    rows = await con.fetch(
        f"{ERRORS_CTE} SELECT e.id, e.stage FROM e {ERRORS_WHERE} AND e.state <> 'locked' AND NOT e.locked "
        f"ORDER BY e.id, e.position", f.get("stage"), f.get("state"), f.get("kind"))
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["id"], []).append(r["stage"])
    return out


# ---------------------------------------------------------------- detail
async def source_detail(con, source_id: str) -> dict | None:
    """Everything about one source (AK-12): base data, lock, stages, locations, events, markdown path."""
    s = await con.fetchrow(
        "SELECT id, title, kind, hash, size, modified, captured, path, deleted, deleted_at, repo_error, "
        "repo_error_at FROM alice.sources WHERE id = $1", source_id)
    if s is None:
        return None
    src = _row(s)
    fm_type = await _frontmatter_type(con, source_id)
    stage_rows = await con.fetch(
        "SELECT ss.stage, ss.state, ss.attempts, ss.last_error AS error, ss.last_attempt_at, ss.next_retry_at, "
        "ss.updated_at FROM alice.source_stages ss JOIN alice.pipeline_stages ps ON ps.name = ss.stage "
        "WHERE ss.source_id = $1 ORDER BY ps.position, ps.name", source_id)
    locs = await con.fetch(
        "SELECT path, mailbox, message_id, present, first_seen, last_seen, gone_at FROM alice.source_locations "
        "WHERE source_id = $1 ORDER BY present DESC, last_seen DESC, id", source_id)
    events = await con.fetch(
        "SELECT level, event, message, created_at FROM alice.source_events WHERE source_id = $1 "
        "ORDER BY created_at DESC, id DESC LIMIT $2", source_id, EVENT_LIMIT)
    can_retry = not src["deleted"] and src["repo_error"] is None
    return {
        **src,
        "type": fm_type,
        "locked": src["repo_error"] is not None,
        "stages": [{**_row(r), "retryable": can_retry and r["state"] in RETRYABLE} for r in stage_rows],
        "locations": [_row(r) for r in locs],
        "events": [_row(r) for r in events],
    }


async def _frontmatter_type(con, source_id: str) -> str | None:
    """Document type (frontmatter `type`) as taken over by the stage `database` (PROJ-119)."""
    return await con.fetchval("SELECT type FROM alice.doc_documents WHERE id = $1", source_id)


async def stage_state(con, source_id: str, stage: str):
    return await con.fetchrow(
        "SELECT s.deleted, s.repo_error, ss.state, ss.attempts FROM alice.sources s "
        "LEFT JOIN alice.source_stages ss ON ss.source_id = s.id AND ss.stage = $2 WHERE s.id = $1",
        source_id, stage)


# ---------------------------------------------------------------- rebuild preview
async def rebuild_preview(con, start_stage: str, kind: str | None) -> dict | None:
    """Approximate scope of a rebuild (AK-20): not deleted, not locked sources of the kind(s) for which a
    stage from the start stage on is not skipped; the stages that run again. None = invalid start stage."""
    st = await stages(con)
    names = [s["name"] for s in st]
    if start_stage not in names or names.index(start_stage) == 0 or start_stage == "detect":
        return None
    following = st[names.index(start_stage):]
    kinds = [kind] if kind else list(KINDS)
    affected = [k for k in kinds if any(k not in s["skip_kinds"] for s in following)]
    n = await con.fetchval(
        "SELECT count(*) FROM alice.sources WHERE NOT deleted AND repo_error IS NULL AND kind = ANY($1::text[])",
        affected)
    run_stages = [s["name"] for s in following if not kind or kind not in s["skip_kinds"]]
    return {"start_stage": start_stage, "kind": kind, "sources": n, "stages": run_stages}
