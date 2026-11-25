"""
Rebuild runs (PROJ-120): a run sets the stages from a start stage on back to pending,
in throttled portions, and the existing stage services work them off. Nothing of the
stage logic lives here.

- Snapshot at the start (alice.rebuild_items): the set of sources is fixed.
- Scope per kind: start stage and every following stage that is not skipped for the kind and
  is served by a stage service (alice.pipeline_stage_served, option A of issue #12).
- Release through the register (POST /rebuild/release): stages → pending, attempt counter 0,
  flagged with the run (normal work first, batch commits — both in the register).
- Throttle: per stage at most N sources of the run pending/running; a source is released
  only when every stage of its scope has room.
- State in PostgreSQL: a restart continues a running run and leaves a paused one paused.
- Progress is computed every few seconds into memory; reading it costs nothing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from .clients import CallError, RegistryClient, Unavailable
from .config import Settings

logger = logging.getLogger("alice-etl-rebuild")

KINDS = ("document", "image", "email", "audio", "video")
ACTIVE = ("running", "paused", "waiting")
RELEASE_CHUNK = 500
STATUS_DE = {"running": "läuft", "paused": "pausiert", "waiting": "wartet", "done": "abgeschlossen",
             "cancelled": "abgebrochen"}


class Rejected(Exception):
    """Start/control rejected (409), with the existing run if there is one."""

    def __init__(self, message: str, run: dict | None = None):
        super().__init__(message)
        self.run = run


class Invalid(Exception):
    pass


class NotFound(Exception):
    pass


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _pairs(scope: dict) -> tuple[list[str], list[str]]:
    kinds, stages = [], []
    for kind, sc in scope.items():
        for st in sc["stages"]:
            kinds.append(kind)
            stages.append(st)
    return kinds, stages


# Per stage of the scope: done (done/skipped), failed (failed, failed_permanent, or blocked because an
# earlier stage of the source failed permanently — in the scope or before the start stage: it can never run), running, open (pending or not
# released yet); `active` = released and pending/running (the throttle counts these).
STATS_SQL = """
WITH fp AS (  -- permanently failed stages of the run's sources, in or before the scope
    SELECT ss.source_id, p.position, p.name
      FROM alice.source_stages ss
      JOIN alice.pipeline_stages p ON p.name = ss.stage
      JOIN alice.rebuild_items fi ON fi.run_id = $1 AND fi.source_id = ss.source_id
     WHERE ss.state = 'failed_permanent'),
r AS (
    SELECT i.source_id, i.released_at IS NOT NULL AS rel, sc.stage, ss.state,
           EXISTS (SELECT 1 FROM fp WHERE fp.source_id = i.source_id
                           AND (fp.position, fp.name) < (ps.position, ps.name)) AS blocked
      FROM alice.rebuild_items i
      JOIN unnest($2::text[], $3::text[]) AS sc(kind, stage) ON sc.kind = i.kind
      JOIN alice.pipeline_stages ps ON ps.name = sc.stage
      LEFT JOIN alice.source_stages ss ON ss.source_id = i.source_id AND ss.stage = sc.stage
     WHERE i.run_id = $1 AND i.excluded IS NULL)
SELECT stage,
       count(*) AS sources,
       count(*) FILTER (WHERE rel AND state IN ('done', 'skipped')) AS done,
       count(*) FILTER (WHERE rel AND state NOT IN ('done', 'skipped')
                        AND (state IN ('failed', 'failed_permanent') OR blocked)) AS failed,
       count(*) FILTER (WHERE rel AND state = 'running' AND NOT blocked) AS running,
       count(*) FILTER (WHERE NOT rel OR (state = 'pending' AND NOT blocked) OR state IS NULL) AS open,
       count(*) FILTER (WHERE rel AND state IN ('pending', 'running') AND NOT blocked) AS active
  FROM r GROUP BY stage
"""

# Released sources whose stages are all through (done, skipped, failed_permanent or blocked).
FINISH_SQL = """
WITH fp AS (  -- permanently failed stages of the run's sources, in or before the scope
    SELECT ss.source_id, p.position, p.name
      FROM alice.source_stages ss
      JOIN alice.pipeline_stages p ON p.name = ss.stage
      JOIN alice.rebuild_items fi ON fi.run_id = $1 AND fi.source_id = ss.source_id
     WHERE ss.state = 'failed_permanent'),
r AS (
    SELECT i.source_id, ss.state,
           EXISTS (SELECT 1 FROM fp WHERE fp.source_id = i.source_id
                           AND (fp.position, fp.name) < (ps.position, ps.name)) AS blocked
      FROM alice.rebuild_items i
      JOIN unnest($2::text[], $3::text[]) AS sc(kind, stage) ON sc.kind = i.kind
      JOIN alice.pipeline_stages ps ON ps.name = sc.stage
      LEFT JOIN alice.source_stages ss ON ss.source_id = i.source_id AND ss.stage = sc.stage
     WHERE i.run_id = $1 AND i.excluded IS NULL AND i.released_at IS NOT NULL AND i.finished_at IS NULL)
UPDATE alice.rebuild_items SET finished_at = NOW()
 WHERE run_id = $1 AND source_id IN (
     SELECT source_id FROM r GROUP BY source_id
     HAVING bool_and(state IN ('done', 'skipped', 'failed_permanent') OR blocked))
"""

BULK_TIMEOUT = "60s"


async def bulk(con):
    """Settings for the queries over all sources of a run (inside a transaction): hash joins instead of
    nested loops, so a stale planner estimate (e.g. right after a large snapshot or registration) can
    never turn them into a full scan per source; and a time limit, so the run loop never hangs."""
    await con.execute("SET LOCAL enable_nestloop = off")
    await con.execute(f"SET LOCAL statement_timeout = '{BULK_TIMEOUT}'")


RUN_COLS = ("id, start_stage, kind, scope, state, reason, started_by, started_at, finished_at, total, "
            "final_counts, reconcile_id")


class Rebuilds:
    def __init__(self, settings: Settings, pool, registry: RegistryClient):
        self.s = settings
        self.pool = pool
        self.registry = registry
        self.cache: dict[int, dict] = {}  # run id → progress (AK-20)
        self.last_log: dict[int, float] = {}
        self.clock = time.monotonic
        self.lock = asyncio.Lock()  # one tick or control action at a time
        self.on_done = None  # callback(run_id) → automatic reconciliation (AK-17)
        self.db_error: str | None = None

    # ================================================================ start
    async def start(self, start_stage: str, kind: str | None, started_by: str) -> dict:
        async with self.lock:
            async with self.pool.acquire() as con, con.transaction():
                await con.execute("SELECT pg_advisory_xact_lock(hashtext('alice-etl-rebuild'))")
                stages = await con.fetch("SELECT name, position, skip_kinds FROM alice.pipeline_stages "
                                         "ORDER BY position, name")
                names = [r["name"] for r in stages]
                if start_stage not in names:
                    raise Invalid(f"Stufe {start_stage} unbekannt")
                if names.index(start_stage) == 0 or start_stage == "detect":
                    raise Invalid(f"{start_stage} ist keine wählbare Startstufe")
                row = await con.fetchrow(f"SELECT {RUN_COLS} FROM alice.rebuild_runs WHERE state = ANY($1::text[]) "
                                         "ORDER BY id LIMIT 1", list(ACTIVE))
                if row:
                    run = self._plain(row)
                    raise Rejected(f"Neuaufbau-Lauf {run['id']} ist bereits aktiv ({STATUS_DE[run['state']]}); "
                                   "erst nach dessen Ende kann ein neuer Lauf starten", run)
                following = stages[names.index(start_stage):]
                served = {(r["stage"], r["kind"]) for r in await con.fetch(
                    "SELECT stage, kind FROM alice.pipeline_stage_served")}
                scope = {}
                for k in ([kind] if kind else KINDS):
                    scope[k] = {
                        "stages": [r["name"] for r in following if k not in r["skip_kinds"] and (r["name"], k) in served],
                        "not_served": [r["name"] for r in following
                                       if k not in r["skip_kinds"] and (r["name"], k) not in served],
                        "skipped": [r["name"] for r in following if k in r["skip_kinds"]],
                    }
                with_stages = [k for k, v in scope.items() if v["stages"]]
                all_skipped = [k for k, v in scope.items() if not v["stages"] and not v["not_served"]]
                run_id = await con.fetchval(
                    "INSERT INTO alice.rebuild_runs (start_stage, kind, scope, started_by) VALUES ($1, $2, $3::jsonb, $4) "
                    "RETURNING id", start_stage, kind, json.dumps(scope), started_by)
                total = int((await con.execute(
                    """
                    INSERT INTO alice.rebuild_items (run_id, source_id, kind, seq, excluded)
                    SELECT $1, s.id, s.kind, row_number() OVER (ORDER BY s.captured, s.id),
                           CASE WHEN s.deleted THEN 'deleted'
                                WHEN s.repo_error IS NOT NULL THEN 'locked'
                                WHEN NOT (s.kind = ANY($2::text[])) THEN
                                     CASE WHEN s.kind = ANY($3::text[]) THEN 'skipped' ELSE 'not_served' END
                           END
                      FROM alice.sources s
                     WHERE ($4::text IS NULL OR s.kind = $4)
                    """, run_id, with_stages, all_skipped, kind)).split()[-1])
                await con.execute("UPDATE alice.rebuild_runs SET total = $2 WHERE id = $1", run_id, total)
            async with self.pool.acquire() as con:
                await con.execute("ANALYZE alice.rebuild_items")  # fresh estimates for the progress queries
            logger.info("Rebuild run %d started by %s: from stage %s, kind %s, %d sources; scope %s",
                        run_id, started_by, start_stage, kind or "all", total,
                        {k: v["stages"] for k, v in scope.items() if v["stages"]})
            self.last_log[run_id] = self.clock()
            progress = await self._refresh(run_id)
        return progress

    # ================================================================ control
    async def control(self, run_id: int, action: str) -> dict:
        allowed = {"pause": ("running", "waiting"), "resume": ("paused",), "cancel": ACTIVE}[action]
        target = {"pause": "paused", "resume": "running", "cancel": "cancelled"}[action]
        async with self.lock:
            async with self.pool.acquire() as con:
                row = await con.fetchrow("SELECT state FROM alice.rebuild_runs WHERE id = $1", run_id)
                if not row:
                    raise NotFound(f"Lauf {run_id} unbekannt")
                if row["state"] not in allowed:
                    raise Rejected(f"Lauf {run_id} ist {STATUS_DE[row['state']]}: {action} nicht möglich")
                await con.execute("UPDATE alice.rebuild_runs SET state = $2, reason = NULL WHERE id = $1",
                                  run_id, target)
            logger.info("Rebuild run %d %s", run_id,
                        {"pause": "paused", "resume": "resumed", "cancel": "cancelled"}[action])
            return await self._refresh(run_id)

    # ================================================================ loop
    async def tick(self) -> None:
        """Release portions, track progress, finish runs. Called every few seconds."""
        async with self.lock:
            try:
                async with self.pool.acquire() as con:
                    rows = await con.fetch(f"SELECT {RUN_COLS} FROM alice.rebuild_runs WHERE state = ANY($1::text[]) "
                                           "OR (state = 'cancelled' AND finished_at IS NULL) ORDER BY id",
                                           list(ACTIVE))
                if self.db_error:
                    logger.info("PostgreSQL reachable again")
                self.db_error = None
            except (OSError, Exception) as exc:  # PostgreSQL away: active runs show `waiting`
                if self.db_error is None:
                    logger.warning("PostgreSQL not reachable, rebuild waits: %s", exc)
                self.db_error = f"PostgreSQL nicht erreichbar: {exc.__class__.__name__}"
                for p in self.cache.values():
                    if p["status"] in ("running", "waiting"):
                        p.update(status="waiting", reason=self.db_error)
                return
            for row in rows:
                run = self._plain(row)
                try:
                    await self._step(run)
                except Unavailable as exc:
                    await self._set_waiting(run, str(exc))
                except Exception:
                    logger.exception("rebuild run %d: step failed", run["id"])

    async def _step(self, run: dict) -> None:
        rid = run["id"]
        if run["state"] in ("running", "waiting"):
            ok, reason = await self.registry.health()
            if not ok:
                await self._set_waiting(run, reason)
            else:
                if run["state"] == "waiting":
                    await self._set_state(rid, "running", None)
                    logger.info("Rebuild run %d continues (%s resolved)", rid, run["reason"])
                    run["state"] = "running"
        async with self.pool.acquire() as con, con.transaction():
            await bulk(con)
            # sources deleted or locked meanwhile are not (any more) part of the run (EC-1)
            await con.execute(
                "UPDATE alice.rebuild_items i SET excluded = CASE WHEN s.deleted THEN 'deleted' ELSE 'locked' END "
                "FROM alice.sources s WHERE i.run_id = $1 AND s.id = i.source_id AND i.excluded IS NULL "
                "AND i.finished_at IS NULL AND (s.deleted OR s.repo_error IS NOT NULL)", rid)
            kinds, stages = _pairs(run["scope"])
            await con.execute(FINISH_SQL, rid, kinds, stages)
        progress = await self._refresh(rid, run)
        if run["state"] == "running":
            await self._release(run, progress)
            progress = await self._refresh(rid)
        if run["state"] == "running" and progress["unreleased"] == 0 and progress["finished"] >= progress["in_run"]:
            await self._finish(run, progress)  # AK-1, EC-4
        elif run["state"] == "cancelled" and progress["released"] <= progress["finished"]:
            await self._finish(run, progress)  # released ones are through (AK-15)
        elif run["state"] in ACTIVE and \
                self.clock() - self.last_log.get(rid, float("-inf")) >= self.s.log_interval_seconds:
            self._log_progress(progress)

    async def _release(self, run: dict, progress: dict) -> None:
        """Release the next sources while every stage of their scope has room (AK-10)."""
        rid, scope = run["id"], run["scope"]
        active = {st: v["active"] for st, v in progress["stages"].items()}
        room = min((self.s.limit(st) - n for st, n in active.items()), default=0)
        if room <= 0 or progress["unreleased"] == 0:
            return
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT source_id, kind FROM alice.rebuild_items WHERE run_id = $1 "
                                   "AND released_at IS NULL AND excluded IS NULL ORDER BY seq LIMIT $2",
                                   rid, max(self.s.limit(st) for st in active) if active else 0)
        portion = []
        for r in rows:
            sts = scope[r["kind"]]["stages"]
            if any(active.get(st, 0) >= self.s.limit(st) for st in sts):
                break  # keep the order: the next source waits for room
            for st in sts:
                active[st] = active.get(st, 0) + 1
            portion.append({"id": r["source_id"], "stages": sts})
        for i in range(0, len(portion), RELEASE_CHUNK):
            chunk = portion[i:i + RELEASE_CHUNK]
            try:
                out = await self.registry.release(rid, chunk)
            except CallError as exc:
                logger.warning("Rebuild run %d: release rejected: %s", rid, exc)
                return
            async with self.pool.acquire() as con:
                await con.execute("UPDATE alice.rebuild_items SET released_at = NOW() WHERE run_id = $1 "
                                  "AND source_id = ANY($2::text[])", rid, out["released"])
                for key, reason in (("deleted", "deleted"), ("unknown", "deleted"), ("locked", "locked")):
                    if out.get(key):
                        await con.execute("UPDATE alice.rebuild_items SET excluded = $3 WHERE run_id = $1 "
                                          "AND source_id = ANY($2::text[])", rid, out[key], reason)

    async def _finish(self, run: dict, progress: dict) -> None:
        rid = run["id"]
        state = "done" if run["state"] == "running" else "cancelled"
        async with self.pool.acquire() as con:
            await con.execute("UPDATE alice.rebuild_runs SET state = $2, reason = NULL, finished_at = NOW(), "
                              "final_counts = $3::jsonb WHERE id = $1", rid, state, json.dumps(progress, default=str))
        progress = await self._refresh(rid)
        async with self.pool.acquire() as con:
            await con.execute("UPDATE alice.rebuild_runs SET final_counts = $2::jsonb WHERE id = $1",
                              rid, json.dumps(progress, default=str))
        logger.info("Rebuild run %d %s: %s", rid, "finished" if state == "done" else "ended after cancel",
                    self._summary_line(progress))
        self.cache.pop(rid, None)
        self.last_log.pop(rid, None)
        if state == "done" and self.on_done:
            self.on_done(rid)

    async def _set_state(self, rid: int, state: str, reason: str | None) -> None:
        async with self.pool.acquire() as con:
            await con.execute("UPDATE alice.rebuild_runs SET state = $2, reason = $3 WHERE id = $1", rid, state, reason)

    async def _set_waiting(self, run: dict, reason: str) -> None:
        if run["state"] != "waiting" or run["reason"] != reason:
            logger.warning("Rebuild run %d waits: %s", run["id"], reason)
            await self._set_state(run["id"], "waiting", reason)
        run.update(state="waiting", reason=reason)
        if run["id"] in self.cache:
            self.cache[run["id"]].update(status="waiting", reason=reason)

    # ================================================================ progress
    def _plain(self, row) -> dict:
        d = dict(row)
        for k in ("scope", "final_counts"):
            if isinstance(d.get(k), str):
                d[k] = json.loads(d[k])
        return d

    async def _refresh(self, rid: int, run: dict | None = None) -> dict:
        """Compute the progress of a run (one bundled query) into the cache (AK-18, AK-20)."""
        async with self.pool.acquire() as con:
            if run is None:
                row = await con.fetchrow(f"SELECT {RUN_COLS} FROM alice.rebuild_runs WHERE id = $1", rid)
                if row is None:
                    raise NotFound(f"Lauf {rid} unbekannt")
                run = self._plain(row)
            kinds, stages = _pairs(run["scope"])
            async with con.transaction():
                await bulk(con)
                per_stage = {r["stage"]: dict(r) for r in await con.fetch(STATS_SQL, rid, kinds, stages)}
            counts = await con.fetchrow(
                "SELECT count(*) AS total, count(*) FILTER (WHERE excluded IS NULL) AS in_run, "
                "count(*) FILTER (WHERE excluded IS NULL AND released_at IS NOT NULL) AS released, "
                "count(*) FILTER (WHERE excluded IS NULL AND finished_at IS NOT NULL) AS finished, "
                "count(*) FILTER (WHERE excluded IS NULL AND finished_at > NOW() - interval '1 hour') AS last_hour "
                "FROM alice.rebuild_items WHERE run_id = $1", rid)
            excluded = {r["excluded"]: r["n"] for r in await con.fetch(
                "SELECT excluded, count(*) AS n FROM alice.rebuild_items WHERE run_id = $1 AND excluded IS NOT NULL "
                "GROUP BY excluded ORDER BY excluded", rid)}
        order = [st for st in dict.fromkeys(stages)]
        stage_out = {st: {k: int(per_stage.get(st, {}).get(k, 0))
                          for k in ("sources", "done", "failed", "running", "open", "active")} for st in order}
        in_run, finished = counts["in_run"], counts["finished"]
        throughput = int(counts["last_hour"])
        remaining = in_run - finished
        progress = {
            "id": rid, "start_stage": run["start_stage"], "kind": run["kind"],
            "scope": run["scope"], "status": run["state"], "status_de": STATUS_DE[run["state"]],
            "reason": run["reason"], "started_by": run["started_by"],
            "started_at": _iso(run["started_at"]), "finished_at": _iso(run["finished_at"]),
            "total": counts["total"], "excluded": excluded, "excluded_total": counts["total"] - in_run,
            "in_run": in_run, "released": counts["released"], "unreleased": in_run - counts["released"],
            "finished": finished, "stages": stage_out,
            "throughput_per_hour": throughput,
            "remaining_seconds": (round(remaining / throughput * 3600) if throughput else (0 if remaining == 0 else None)),
            "reconcile_id": run.get("reconcile_id"),
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
        if run["state"] in ACTIVE or (run["state"] == "cancelled" and run["finished_at"] is None):
            self.cache[rid] = progress
        return progress

    async def progress(self, rid: int) -> dict:
        """Served from memory for active runs (no database, NAS or repo access, AK-20)."""
        if rid in self.cache:
            return self.cache[rid]
        async with self.pool.acquire() as con:
            row = await con.fetchrow(f"SELECT {RUN_COLS} FROM alice.rebuild_runs WHERE id = $1", rid)
        if row is None:
            raise NotFound(f"Lauf {rid} unbekannt")
        run = self._plain(row)
        if run["final_counts"] and run["finished_at"]:
            p = dict(run["final_counts"])
            p.update(status=run["state"], status_de=STATUS_DE[run["state"]], reason=run["reason"],
                     finished_at=_iso(run["finished_at"]), reconcile_id=run["reconcile_id"])
            return p
        return await self._refresh(rid, run)

    async def current_id(self) -> int | None:
        if self.cache:
            return min(self.cache)
        async with self.pool.acquire() as con:
            return await con.fetchval("SELECT id FROM alice.rebuild_runs ORDER BY id DESC LIMIT 1")

    async def list_runs(self, limit: int, offset: int) -> dict:
        async with self.pool.acquire() as con:
            total = await con.fetchval("SELECT count(*) FROM alice.rebuild_runs")
            ids = [r["id"] for r in await con.fetch("SELECT id FROM alice.rebuild_runs ORDER BY id DESC "
                                                    "LIMIT $1 OFFSET $2", limit, offset)]
        return {"total": total, "items": [await self.progress(i) for i in ids]}

    async def errors(self, rid: int, limit: int, offset: int) -> dict:
        """Failed stages of the run's released sources: id, title, stage, message (AK-19). Includes a stage
        before the start stage that failed permanently: it blocks the source's scope."""
        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT scope FROM alice.rebuild_runs WHERE id = $1", rid)
            if row is None:
                raise NotFound(f"Lauf {rid} unbekannt")
            scope = row["scope"] if isinstance(row["scope"], dict) else json.loads(row["scope"])
            kinds, stages = _pairs(scope)
            base = """
                FROM alice.rebuild_items i
                JOIN alice.source_stages ss ON ss.source_id = i.source_id
                LEFT JOIN unnest($2::text[], $3::text[]) AS sc(kind, stage)
                       ON sc.kind = i.kind AND sc.stage = ss.stage
                JOIN alice.sources s ON s.id = i.source_id
                JOIN alice.pipeline_stages ps ON ps.name = ss.stage
               WHERE i.run_id = $1 AND i.excluded IS NULL AND i.released_at IS NOT NULL
                 AND (ss.state = 'failed_permanent' OR (ss.state = 'failed' AND sc.stage IS NOT NULL))"""
            async with con.transaction():
                await bulk(con)
                total = await con.fetchval("SELECT count(*) " + base, rid, kinds, stages)
                rows = await con.fetch("SELECT s.id, s.title, ss.stage, ss.state, ss.attempts, ss.last_error AS error, "
                                       "ss.last_attempt_at " + base + " ORDER BY ss.last_attempt_at DESC NULLS LAST, "
                                       "s.id, ps.position LIMIT $4 OFFSET $5", rid, kinds, stages, limit, offset)
        return {"total": total, "items": [{k: _iso(v) for k, v in dict(r).items()} for r in rows]}

    # ================================================================ log
    @staticmethod
    def _summary_line(p: dict) -> str:
        stages = ", ".join(f"{st} {v['done']}/{v['sources']} erledigt, {v['failed']} fehlgeschlagen"
                           for st, v in p["stages"].items())
        return (f"{p['in_run']} Quellen ({p['excluded_total']} ausgenommen), {p['finished']} durch; {stages}; "
                f"{p['throughput_per_hour']}/h")

    def _log_progress(self, p: dict) -> None:
        self.last_log[p["id"]] = self.clock()
        rest = p["remaining_seconds"]
        logger.info("Rebuild run %d progress (%s): %s; released %d/%d; remaining %s", p["id"], p["status"],
                    self._summary_line(p), p["released"], p["in_run"],
                    "unbekannt" if rest is None else f"{rest // 3600} h {rest % 3600 // 60} min")
