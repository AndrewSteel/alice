"""
Completeness reconciliation (PROJ-120): NAS <-> register <-> repo <-> stages <-> DB.

1. Take the lease of alice-file-detection (no nightly run meanwhile, AK-35).
2. Check every level without changing anything:
   level 1 NAS <-> register (detection), re-hash portion / full re-hash (detection),
   level 2 register <-> repo (register), level 3 stages and level 4 register <-> DB (own queries).
3. Safeguard: more planned repairs than the limit (default 5 % of the sources) → repair nothing.
4. Repair the unambiguous gaps (through the detection / the register; orphaned document rows
   directly), one event per repair at the source.
5. Store the result + gaps, one log entry; drop results older than the retention.
Register/repo or PostgreSQL unreachable → abort, result `incomplete`, no further repairs (AK-41).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from .clients import Busy, CallError, DetectionClient, RegistryClient, Unavailable
from .config import Settings

logger = logging.getLogger("alice-etl-rebuild.reconcile")

LEASE_SECONDS = 300
LEASE_RENEW_SECONDS = 60
LEASE_WAIT_SECONDS = 30
GAP_LIST_LIMIT = 10000  # stored gap rows per level and result; the counts are always complete
ACTIVE_RUN = ("running", "paused", "waiting")

LEVEL3_SQL = """
SELECT s.id, s.title, ss.stage, ss.updated_at
  FROM alice.source_stages ss
  JOIN alice.sources s ON s.id = ss.source_id
  JOIN alice.pipeline_stage_served sv ON sv.stage = ss.stage AND sv.kind = s.kind
  JOIN alice.pipeline_stages ps ON ps.name = ss.stage
 WHERE NOT s.deleted AND s.repo_error IS NULL AND ss.state = 'pending'
   AND ss.updated_at < NOW() - make_interval(secs => $1::float8)
   -- consequence of a visible error of an earlier stage: not a silent gap
   AND NOT EXISTS (SELECT 1 FROM alice.source_stages e JOIN alice.pipeline_stages pe ON pe.name = e.stage
                    WHERE e.source_id = ss.source_id AND pe.position < ps.position
                      AND e.state IN ('failed', 'failed_permanent'))
   -- open in an active rebuild run (AK-29, EC-6)
   AND NOT EXISTS (SELECT 1 FROM alice.rebuild_items i JOIN alice.rebuild_runs r ON r.id = i.run_id
                    WHERE i.source_id = ss.source_id AND r.state = ANY($2::text[])
                      AND i.excluded IS NULL AND i.finished_at IS NULL)
 ORDER BY ss.updated_at, s.id
"""

LEVEL4_MISSING_SQL = """
SELECT s.id, s.title FROM alice.sources s
  JOIN alice.source_stages ss ON ss.source_id = s.id AND ss.stage = 'database'
 WHERE s.kind = 'document' AND NOT s.deleted AND ss.state = 'done'
   AND NOT EXISTS (SELECT 1 FROM alice.doc_documents d WHERE d.id = s.id)
 ORDER BY s.id
"""

LEVEL4_ORPHAN_SQL = """
SELECT d.id, s.id IS NULL AS unknown FROM alice.doc_documents d
  LEFT JOIN alice.sources s ON s.id = d.id
 WHERE s.id IS NULL OR s.deleted ORDER BY d.id
"""


class Busy409(Exception):
    """A reconciliation is already running (EC-12)."""


class DetectionFailed(Exception):
    """The detection could not check level 1 / re-hash: result incomplete, the other levels still run."""


class Abort(Exception):
    """Register/repo or PostgreSQL unreachable: stop, result incomplete (AK-41)."""


def _gap(level: int, gap: str, *, source_id=None, path=None, detail=None, repair=None) -> dict:
    return {"level": level, "gap": gap, "source_id": source_id, "path": path, "detail": detail,
            "repair": repair, "action": "reported"}


class Reconciler:
    def __init__(self, settings: Settings, pool, registry: RegistryClient, detection: DetectionClient):
        self.s = settings
        self.pool = pool
        self.registry = registry
        self.detection = detection
        self.task: asyncio.Task | None = None
        self.current: int | None = None
        self.last_nightly_attempt = float("-inf")

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    # ================================================================ start
    async def start(self, kind: str, mode: str = "levels", rebuild_run: int | None = None) -> int:
        if self.running:
            raise Busy409(f"Abgleich {self.current} läuft noch")
        async with self.pool.acquire() as con:
            rid = await con.fetchval("INSERT INTO alice.reconcile_results (kind, mode, rebuild_run_id) "
                                     "VALUES ($1, $2, $3) RETURNING id", kind, mode, rebuild_run)
            if rebuild_run:
                await con.execute("UPDATE alice.rebuild_runs SET reconcile_id = $2 WHERE id = $1", rebuild_run, rid)
        self.current = rid
        self.task = asyncio.create_task(self._run(rid, kind, mode))
        return rid

    async def mark_interrupted(self) -> int:
        async with self.pool.acquire() as con:
            res = await con.execute("UPDATE alice.reconcile_results SET state = 'incomplete', finished_at = NOW(), "
                                    "reason = 'Dienst während des Abgleichs neu gestartet' WHERE state = 'running'")
        return int(res.split()[-1])

    # ================================================================ schedule
    def nightly_slot(self, now: datetime) -> datetime:
        local = now.astimezone(self.s.tz)
        slot = datetime.combine(local.date(), self.s.nightly, tzinfo=self.s.tz)
        if slot > local:
            slot = datetime.combine(local.date() - timedelta(days=1), self.s.nightly, tzinfo=self.s.tz)
        return slot.astimezone(timezone.utc)

    async def nightly_due(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        slot = self.nightly_slot(now)
        if now - slot > timedelta(hours=self.s.catchup_hours):
            return False
        async with self.pool.acquire() as con:
            return not await con.fetchval("SELECT EXISTS (SELECT 1 FROM alice.reconcile_results WHERE kind = 'nightly' "
                                          "AND state = 'complete' AND started_at >= $1)", slot)

    async def tick(self) -> None:
        if self.running:
            return
        async with self.pool.acquire() as con:  # a finished run without its reconciliation yet (AK-17)
            run = await con.fetchval("SELECT id FROM alice.rebuild_runs WHERE state = 'done' AND reconcile_id IS NULL "
                                     "ORDER BY id LIMIT 1")
        if run:
            await self.start("after_rebuild", rebuild_run=run)
        elif await self.nightly_due() and time.monotonic() - self.last_nightly_attempt >= 600:
            self.last_nightly_attempt = time.monotonic()
            await self.start("nightly")

    # ================================================================ run
    async def _run(self, rid: int, kind: str, mode: str) -> None:
        t0 = time.monotonic()
        gaps: list[dict] = []
        summary: dict = {"levels": {}, "skipped_folders": [], "hash_cycle": None, "notes": []}
        state, reason, guard = "complete", None, False
        lease = None
        renew = None
        try:
            lease = await self._lease()
            if lease is None:
                summary["notes"].append("Datei-Erkennung nicht erreichbar: Ebene 1 nicht geprüft")
            else:
                renew = asyncio.create_task(self._renew(lease))
            # ---- check
            detection_error = None
            if lease is not None:
                try:
                    if mode == "levels":
                        gaps += await self._level1(summary)
                    if mode == "full_rehash" or kind == "nightly":
                        gaps += await self._rehash(summary, full=mode == "full_rehash")
                except DetectionFailed as exc:
                    detection_error = str(exc)
                    summary["notes"].append(detection_error)
            if mode == "levels":
                gaps += await self._level2()
                gaps += await self._level3()
                gaps += await self._level4()
            # ---- safeguard (AK-33)
            planned = [g for g in gaps if g["repair"]]
            async with self.pool.acquire() as con:
                total_sources = await con.fetchval("SELECT count(*) FROM alice.sources")
            limit = total_sources * self.s.repair_limit_percent / 100.0
            summary["planned_repairs"] = len(planned)
            summary["sources"] = total_sources
            if planned and len(planned) > limit:
                guard = True
                summary["notes"].append(
                    f"Sicherung gegen Massenreparatur: {len(planned)} Reparaturen bei {total_sources} Quellen "
                    f"> {self.s.repair_limit_percent} %, nichts repariert")
                logger.warning("Reconciliation %d: %d repairs for %d sources exceed %s %%, nothing repaired",
                               rid, len(planned), total_sources, self.s.repair_limit_percent)
            else:
                await self._repair(planned)
            if lease is None:
                state, reason = "incomplete", "Datei-Erkennung nicht erreichbar: Ebene 1 nicht geprüft"
            elif detection_error:
                state, reason = "incomplete", detection_error
        except Abort as exc:
            state, reason = "incomplete", str(exc)
            logger.warning("Reconciliation %d aborted: %s", rid, exc)
        except Exception as exc:
            state, reason = "incomplete", f"Fehler im Abgleich: {exc.__class__.__name__}: {exc}"
            logger.exception("Reconciliation %d failed", rid)
        finally:
            if renew:
                renew.cancel()
            if lease:
                try:
                    await self.detection.unlease(lease)
                except Exception:
                    pass  # expires by itself
        summary["levels"] = self._level_summary(gaps)
        summary["duration_seconds"] = round(time.monotonic() - t0, 1)
        await self._save(rid, state, reason, guard, summary, gaps)
        logger.info("Reconciliation %d (%s, %s) %s in %.1f s%s: %s", rid, kind, mode, state,
                    summary["duration_seconds"], f" ({reason})" if reason else "",
                    json.dumps(summary["levels"]))

    async def _lease(self) -> str | None:
        """Wait for the nightly run to end, then hold the lease; None if the detection is unreachable."""
        while True:
            try:
                return await self.detection.lease(None, LEASE_SECONDS)
            except Busy:
                logger.info("Nightly run of the detection is active, reconciliation waits")
                await asyncio.sleep(LEASE_WAIT_SECONDS)
            except (Unavailable, CallError) as exc:
                logger.warning("Detection not reachable, level 1 skipped: %s", exc)
                return None

    async def _renew(self, token: str) -> None:
        while True:
            await asyncio.sleep(LEASE_RENEW_SECONDS)
            try:
                await self.detection.lease(token, LEASE_SECONDS)
            except Exception as exc:
                logger.warning("Lease renewal failed: %s", exc)

    # ================================================================ levels
    async def _level1(self, summary: dict) -> list[dict]:
        try:
            out = await self.detection.check(self.s.long_timeout_seconds)
        except (Unavailable, Busy, CallError) as exc:
            raise DetectionFailed(f"Datei-Erkennung: Ebene 1 nicht geprüft ({exc})") from exc
        summary["skipped_folders"] = out["skipped_folders"]
        gaps = [_gap(1, "file_unregistered", path=u["path"], detail=f"Ordner {u['folder']}", repair="register")
                for u in out["unregistered"]]
        gaps += [_gap(1, "file_missing", source_id=m["source_id"], path=m["path"],
                      detail="Fundort im Register vorhanden, Datei fehlt (Entfernen macht der Nachtlauf)")
                 for m in out["missing"]]
        gaps += [_gap(1, "folder_skipped", path=f["folder"], detail=f["reason"]) for f in out["skipped_folders"]]
        return gaps

    async def _rehash(self, summary: dict, full: bool) -> list[dict]:
        try:
            out = await self.detection.rehash(
                full=full, cycle_days=self.s.hash_cycle_days,
                max_seconds=None if full else self.s.hash_portion_seconds,
                max_bytes=None if full else self.s.hash_portion_bytes, timeout=self.s.long_timeout_seconds)
        except (Unavailable, Busy, CallError) as exc:
            raise DetectionFailed(f"Datei-Erkennung: Neu-Hashen nicht möglich ({exc})") from exc
        summary["hash_cycle"] = {**out["cycle"], "hashed": out["hashed"], "bytes": out["bytes"]}
        gaps = [_gap(1, "hash_changed", source_id=m["source_id"], path=m["path"],
                     detail=f"neuer Hash {m['hash']}", repair="apply") for m in out["mismatches"]]
        gaps += [_gap(1, "file_unreadable", source_id=u["source_id"], path=u["path"], detail=u["detail"])
                 for u in out["unreadable"]]
        gaps += [_gap(1, "file_vanished", source_id=v["source_id"], path=v["path"],
                      detail="Datei beim Neu-Hashen nicht gefunden") for v in out["vanished"]]
        return gaps

    async def _level2(self) -> list[dict]:
        try:
            out = await self.registry.repo_check(self.s.long_timeout_seconds)
        except (Unavailable, Busy, CallError) as exc:
            raise Abort(f"Register/Repo nicht erreichbar: {exc}") from exc
        gaps = []
        for f in out["findings"]:
            g = _gap(2, f["gap"], source_id=f.get("id"), path=f.get("path"), detail=f.get("detail"),
                     repair=f.get("action"))
            g["found_at"] = f.get("found_at")
            gaps.append(g)
        return gaps

    async def _level3(self) -> list[dict]:
        try:
            async with self.pool.acquire() as con, con.transaction():
                await con.execute("SET LOCAL enable_nestloop = off")  # robust against stale estimates
                rows = await con.fetch(LEVEL3_SQL, self.s.pending_limit_hours * 3600, list(ACTIVE_RUN))
        except (OSError, asyncio.TimeoutError) as exc:
            raise Abort(f"PostgreSQL nicht erreichbar: {exc}") from exc
        return [_gap(3, "stage_pending_too_long", source_id=r["id"],
                     detail=f"{r['title']}: Stufe {r['stage']} seit {r['updated_at'].isoformat()} pending")
                for r in rows]

    async def _level4(self) -> list[dict]:
        async with self.pool.acquire() as con:
            missing = await con.fetch(LEVEL4_MISSING_SQL)
            orphans = await con.fetch(LEVEL4_ORPHAN_SQL)
        gaps = [_gap(4, "db_row_missing", source_id=r["id"],
                     detail=f"{r['title']}: database = done, Dokument-Zeile fehlt", repair="db_retry")
                for r in missing]
        gaps += [_gap(4, "db_row_orphan", source_id=r["id"],
                      detail="Dokument-Zeile zu unbekannter Quelle" if r["unknown"] else
                      "Dokument-Zeile zu gelöschter Quelle", repair="db_delete") for r in orphans]
        return gaps

    # ================================================================ repairs
    async def _repair(self, planned: list[dict]) -> None:
        """Every repair goes through the owning service; each gets an event at its source (AK-34)."""
        by = {}
        for g in planned:
            by.setdefault(g["repair"], []).append(g)
        try:
            if by.get("register"):
                await self._repair_register(by["register"])
            if by.get("apply"):
                await self._repair_apply(by["apply"])
            level2 = by.get("restore", []) + by.get("move", [])
            if level2:
                await self._repair_level2(level2)
            for g in by.get("db_retry", []):
                await self.registry.retry(g["source_id"], "database")
                await self._event(g, "reconcile_db_retry",
                                  "Abgleich: Dokument-Zeile fehlte trotz database = done, Stufe database erneut")
            for g in by.get("db_delete", []):
                async with self.pool.acquire() as con:
                    await con.execute("DELETE FROM alice.doc_documents WHERE id = $1", g["source_id"])
                g["action"] = "repaired"
                if "unbekannt" not in g["detail"]:
                    await self._event(g, "reconcile_db_removed",
                                      "Abgleich: Dokument-Zeile der gelöschten Quelle samt abhängigen Daten entfernt")
        except (Unavailable, OSError, asyncio.TimeoutError) as exc:
            raise Abort(f"Register/Repo bzw. PostgreSQL während der Reparatur nicht erreichbar: {exc}") from exc

    async def _event(self, g: dict, event: str, message: str) -> None:
        g["action"] = "repaired"
        try:
            await self.registry.event(g["source_id"], event, message)
        except CallError as exc:
            logger.warning("Event for %s not stored: %s", g["source_id"], exc)

    async def _repair_register(self, gaps: list[dict]) -> None:
        try:
            out = await self.detection.register([g["path"] for g in gaps], self.s.long_timeout_seconds)
        except (Busy, CallError) as exc:
            for g in gaps:
                g.update(action="repair_failed", detail=f"{g['detail']}; {exc}")
            return
        except Unavailable as exc:
            for g in gaps:
                g.update(action="repair_failed", detail=f"{g['detail']}; {exc}")
            return
        res = {r["path"]: r for r in out["results"]}
        for g in gaps:
            r = res.get(g["path"], {})
            if r.get("registered"):
                g["source_id"] = r["source_id"]
                await self._event(g, "reconcile_registered",
                                  f"Abgleich: nicht registrierte Datei {g['path']} registriert")
            else:
                g.update(action="repair_failed", detail=f"{g['detail']}; {r.get('detail', 'nicht registriert')}")

    async def _repair_apply(self, gaps: list[dict]) -> None:
        try:
            out = await self.detection.apply([g["path"] for g in gaps], self.s.long_timeout_seconds)
        except (Busy, CallError, Unavailable) as exc:
            for g in gaps:
                g.update(action="repair_failed", detail=f"{g['detail']}; {exc}")
            return
        res = {r["path"]: r for r in out["results"]}
        for g in gaps:
            r = res.get(g["path"], {})
            if r.get("applied"):
                await self._event(g, "reconcile_hash_changed",
                                  f"Abgleich: Inhalt von {g['path']} geändert (Neu-Hashen), wie ein geändertes "
                                  "Original behandelt")
            else:
                g.update(action="repair_failed", detail=f"{g['detail']}; {r.get('detail', 'nicht angewendet')}")

    async def _repair_level2(self, gaps: list[dict]) -> None:
        items = [{"id": g["source_id"], "action": g["repair"],
                  **({"found_at": g["found_at"]} if g.get("found_at") else {})} for g in gaps]
        try:
            out = await self.registry.repo_repair(items, self.s.long_timeout_seconds)
        except CallError as exc:
            for g in gaps:
                g.update(action="repair_failed", detail=f"{g.get('detail') or ''}; {exc}")
            return
        res = {r["id"]: r for r in out["results"]}
        for g in gaps:
            r = res.get(g["source_id"], {})
            if r.get("repaired"):
                g["action"] = "repaired"  # the register stored the event
                g["detail"] = f"{g.get('detail') or ''} → {r.get('how')}: {r.get('path')}".strip(" →")
            else:
                g.update(action="repair_failed", detail=f"{g.get('detail') or ''}; {r.get('detail', '')}")

    # ================================================================ result
    @staticmethod
    def _level_summary(gaps: list[dict]) -> dict:
        out = {str(lv): {"gaps": 0, "repaired": 0, "reported": 0, "repair_failed": 0, "by_gap": {}} for lv in (1, 2, 3, 4)}
        for g in gaps:
            if g["gap"] == "folder_skipped":
                continue  # listed separately, not a gap of a source
            lv = out[str(g["level"])]
            lv["gaps"] += 1
            lv[g["action"]] += 1
            lv["by_gap"][g["gap"]] = lv["by_gap"].get(g["gap"], 0) + 1
        return out

    async def _save(self, rid: int, state: str, reason: str | None, guard: bool, summary: dict,
                    gaps: list[dict]) -> None:
        per_level: dict[int, int] = {}
        rows = []
        for g in gaps:
            per_level[g["level"]] = per_level.get(g["level"], 0) + 1
            if per_level[g["level"]] <= GAP_LIST_LIMIT:
                rows.append((rid, g["level"], g["gap"], g["source_id"], g["path"], g["detail"], g["action"]))
        summary["gap_list_truncated"] = {str(lv): n - GAP_LIST_LIMIT for lv, n in per_level.items() if n > GAP_LIST_LIMIT}
        for attempt in range(30):  # PostgreSQL may be the reason for the abort: keep the result when it is back
            try:
                async with self.pool.acquire() as con, con.transaction():
                    await con.execute("UPDATE alice.reconcile_results SET state = $2, reason = $3, guard_triggered = $4, "
                                      "finished_at = NOW(), summary = $5::jsonb WHERE id = $1",
                                      rid, state, reason, guard, json.dumps(summary, default=str))
                    await con.executemany("INSERT INTO alice.reconcile_gaps (result_id, level, gap, source_id, path, "
                                          "detail, action) VALUES ($1, $2, $3, $4, $5, $6, $7)", rows)
                    await con.execute("DELETE FROM alice.reconcile_results WHERE started_at < NOW() - "
                                      "make_interval(days => $1)", self.s.keep_days)
                return
            except (OSError, asyncio.TimeoutError) as exc:
                logger.warning("Result %d not stored yet (%s), retrying", rid, exc)
                await asyncio.sleep(10)

    # ================================================================ read
    async def list_results(self, limit: int, offset: int) -> dict:
        async with self.pool.acquire() as con:
            total = await con.fetchval("SELECT count(*) FROM alice.reconcile_results")
            rows = await con.fetch("SELECT * FROM alice.reconcile_results ORDER BY started_at DESC, id DESC "
                                   "LIMIT $1 OFFSET $2", limit, offset)
        return {"total": total, "items": [self._result(r) for r in rows]}

    async def get_result(self, rid: int) -> dict | None:
        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM alice.reconcile_results WHERE id = $1", rid)
        return self._result(row) if row else None

    async def gaps(self, rid: int, level: int | None, limit: int, offset: int) -> dict:
        async with self.pool.acquire() as con:
            total = await con.fetchval("SELECT count(*) FROM alice.reconcile_gaps WHERE result_id = $1 "
                                       "AND ($2::int IS NULL OR level = $2)", rid, level)
            rows = await con.fetch("SELECT level, gap, source_id, path, detail, action FROM alice.reconcile_gaps "
                                   "WHERE result_id = $1 AND ($2::int IS NULL OR level = $2) ORDER BY level, id "
                                   "LIMIT $3 OFFSET $4", rid, level, limit, offset)
        return {"total": total, "items": [dict(r) for r in rows]}

    @staticmethod
    def _result(row) -> dict:
        d = dict(row)
        if isinstance(d.get("summary"), str):
            d["summary"] = json.loads(d["summary"])
        dur = (d["finished_at"] - d["started_at"]).total_seconds() if d.get("finished_at") else None
        d["duration_seconds"] = round(dur, 1) if dur is not None else None
        d["status_de"] = {"running": "läuft", "complete": "vollständig", "incomplete": "unvollständig"}[d["state"]]
        return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in d.items()}
