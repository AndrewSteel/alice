"""
Level 1 of the completeness reconciliation (PROJ-120): NAS <-> register.

Called by alice-etl-rebuild. Checking and repairing are separate calls, so the caller can
apply its safeguard against mass repairs before anything changes:
- check:   full listing of all active watched folders (same rules as the nightly run) compared
           with the present locations in the register → unregistered files, missing files,
           skipped folders. Changes nothing.
- register: register given files like newly found ones (stability + hash, PROJ-116 rules).
- rehash:  rolling re-hash of the known originals (one cycle = every known path once); reports
           differing hashes, unreadable and vanished files. Changes nothing but the progress.
- apply:   treat differing hashes like an original changed in place (PROJ-116 rules incl. EC-9).
- lease:   while a reconciliation holds the lease no nightly run starts, and no lease is
           granted while a nightly run is active (AK-35). It expires by itself.
Originals are only ever opened for reading.
"""
from __future__ import annotations

import asyncio
import logging
import math
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from . import fsscan
from .detector import Busy, Detector, Stats

logger = logging.getLogger("alice-file-detection.reconcile")

EXCLUSIVE_WAIT_SECONDS = 600
BATCH_THRESHOLD = 20


class LeaseHeld(Exception):
    pass


# ================================================================ lease (AK-35)
def lease_active(det: Detector) -> bool:
    return det.lease is not None and det.lease[1] > time.monotonic()


def acquire_lease(det: Detector, token: str | None, seconds: int) -> str:
    if det.running == "night":
        raise Busy("night")
    if lease_active(det) and det.lease[0] != token:
        raise LeaseHeld("Ein anderer Abgleich hält die Sperre")
    token = token if token and lease_active(det) and det.lease[0] == token else secrets.token_hex(16)
    det.lease = (token, time.monotonic() + seconds)
    return token


def release_lease(det: Detector, token: str) -> bool:
    if det.lease and det.lease[0] == token:
        det.lease = None
        return True
    return False


@asynccontextmanager
async def exclusive(det: Detector):
    """Wait until no day scan runs, then block scans for the duration of the call."""
    deadline = time.monotonic() + EXCLUSIVE_WAIT_SECONDS
    while det.running:
        if det.running == "night" or time.monotonic() > deadline:
            raise Busy(det.running)
        await asyncio.sleep(0.2)
    det.running = "reconcile"
    try:
        yield
    finally:
        det.running = None


# ================================================================ helpers
def _owner(path: str, folder_paths) -> str | None:
    """Watched folder a path belongs to: the longest matching one (PROJ-116 AK-21)."""
    best = None
    for f in folder_paths:
        if fsscan.under(path, f) and (best is None or len(f) > len(best)):
            best = f
    return best


async def _active_folders(det: Detector, stats: Stats) -> tuple[list, list[str], list[str]]:
    """(all folders, checkable folder paths, protected paths) with the nightly-run rules."""
    folders = await det.folders()
    ok, protected = [], []
    for f in folders:
        if not f.enabled or det.excluded(f.path) or not await det.check_folder(f.path, stats):
            protected.append(f.path)
        else:
            ok.append(f.path)
    return folders, ok, protected


# ================================================================ check
async def check(det: Detector) -> dict:
    stats = Stats("reconcile")
    async with exclusive(det):
        folders, ok, protected = await _active_folders(det, stats)
        folder_paths = {f.path for f in folders}
        listed: dict[str, tuple[str, int, int]] = {}
        walked: list[str] = []
        for folder in ok:
            unreadable: list[str] = []
            async for e in det._walk(folder, folder_paths, stats, unreadable):
                if fsscan.kind_of(e.name, det.s) is not None:
                    listed[e.path] = (folder, e.size, e.mtime_ns)
            protected.extend(unreadable)
            walked.append(folder)
        async with det.pool.acquire() as con:
            rows = await con.fetch("SELECT l.path, l.source_id FROM alice.source_locations l "
                                   "WHERE l.present AND l.path IS NOT NULL")
    present = {r["path"]: r["source_id"] for r in rows}
    unregistered = [{"path": p, "folder": f, "size": size, "mtime_ns": mt}
                    for p, (f, size, mt) in sorted(listed.items()) if p not in present]
    walked_set = set(walked)
    missing = []
    for path, sid in sorted(present.items()):
        if path in listed:
            continue
        owner = _owner(path, folder_paths)
        if owner is None or owner not in walked_set or any(fsscan.under(path, p) for p in protected):
            continue  # not watched, disabled, skipped or unreadable: never counts as missing (AK-42, EC-8)
        missing.append({"path": path, "source_id": sid, "folder": owner})
    return {"files": len(listed), "unregistered": unregistered, "missing": missing,
            "skipped_folders": stats.skipped_folders, "folders": walked}


# ================================================================ register
async def register(det: Detector, items: list[dict]) -> dict:
    """Register unregistered files like newly found ones (AK-23)."""
    stats = Stats("reconcile")
    results = []
    async with exclusive(det):
        folders = {f.path for f in await det.folders() if f.enabled}
        batch = len(items) > BATCH_THRESHOLD
        for it in items:
            path = it["path"]
            folder = _owner(path, folders)
            st = await asyncio.to_thread(fsscan.file_stat, path)
            if folder is None or st is None:
                results.append({"path": path, "registered": False, "detail": "Datei nicht mehr vorhanden"
                                if st is None else "kein aktiver überwachter Ordner"})
                continue
            ok = await det.take_new(path, folder, st[0], st[1], stats, batch=batch)
            sid = None
            if ok:
                async with det.pool.acquire() as con:
                    sid = await con.fetchval("SELECT source_id FROM alice.detect_files WHERE path = $1", path)
            results.append({"path": path, "registered": ok, "source_id": sid,
                            **({} if ok else {"detail": "nicht stabil oder nicht lesbar (nächster Lauf)"})})
        if stats.registered_batch:
            await det.registry.flush()
    return {"results": results, "new_sources": stats.new_sources, "new_locations": stats.new_locations}


# ================================================================ rolling re-hash
async def _cycle_start(con, now: datetime) -> datetime:
    started = await con.fetchval("SELECT started_at FROM alice.detect_hash_cycle WHERE id = 1")
    if started is None:
        started = await con.fetchval("INSERT INTO alice.detect_hash_cycle (id, started_at) VALUES (1, $1) "
                                     "ON CONFLICT (id) DO UPDATE SET started_at = alice.detect_hash_cycle.started_at "
                                     "RETURNING started_at", now)
    return started


async def _new_cycle(con, now: datetime) -> datetime:
    return await con.fetchval("INSERT INTO alice.detect_hash_cycle (id, started_at) VALUES (1, $1) "
                              "ON CONFLICT (id) DO UPDATE SET started_at = EXCLUDED.started_at RETURNING started_at",
                              now)


async def _cycle_progress(con, folders: list[str], started: datetime) -> dict:
    row = await con.fetchrow("SELECT count(*) AS total, count(*) FILTER (WHERE rehashed_at >= $2) AS done "
                             "FROM alice.detect_files WHERE folder = ANY($1::text[])", folders, started)
    total, done = row["total"], row["done"]
    return {"started_at": started.isoformat(), "done": done, "total": total,
            "percent": round(100.0 * done / total, 1) if total else 100.0}


async def rehash(det: Detector, *, full: bool = False, cycle_days: float = 30, max_seconds: float | None = None,
                 max_bytes: int | None = None, now: datetime | None = None) -> dict:
    """One portion of the rolling re-hash (nightly), or all known originals (`full`, on demand).
    Progress is stored after every file, so a restart continues at the same place (AK-36, AK-37)."""
    now = now or datetime.now(timezone.utc)
    stats = Stats("rehash")
    _, ok, _ = await _active_folders(det, stats)
    async with det.pool.acquire() as con:
        started = await (_new_cycle(con, now) if full else _cycle_start(con, now))
        query = ("SELECT f.path, f.source_id, f.folder, f.size, s.hash FROM alice.detect_files f "
                 "JOIN alice.sources s ON s.id = f.source_id WHERE f.folder = ANY($1::text[]) "
                 "AND (f.rehashed_at IS NULL OR f.rehashed_at < $2) ORDER BY f.rehashed_at NULLS FIRST, f.path")
        rows = await con.fetch(query, ok, started)
        if not rows and not full and now - started >= timedelta(days=cycle_days):
            started = await _new_cycle(con, now)  # cycle done and due again: next one
            rows = await con.fetch(query, ok, started)
        total_bytes = await con.fetchval("SELECT COALESCE(sum(size), 0) FROM alice.detect_files "
                                         "WHERE folder = ANY($1::text[])", ok)
    budget = None if full else (max_bytes or math.ceil(int(total_bytes) / max(float(cycle_days), 1e-9)))
    t0 = time.monotonic()
    hashed = hashed_bytes = 0
    mismatches, unreadable, vanished = [], [], []
    for r in rows:
        if budget is not None and hashed_bytes >= budget:
            break
        if not full and max_seconds is not None and time.monotonic() - t0 >= max_seconds:
            break
        path = r["path"]
        try:
            h = await asyncio.to_thread(fsscan.sha256_file, path)  # whole file, also very large ones (EC-10)
        except FileNotFoundError:
            vanished.append({"path": path, "source_id": r["source_id"]})
            continue
        except OSError as exc:  # reported, progress not stored: tried again next time (AK-43)
            unreadable.append({"path": path, "source_id": r["source_id"], "detail": fsscan.problem_cause(exc)})
            continue
        hashed += 1
        hashed_bytes += r["size"]
        if h != r["hash"]:  # reported only; progress stored when the change has been applied
            mismatches.append({"path": path, "source_id": r["source_id"], "hash": h})
            continue
        async with det.pool.acquire() as con:
            await con.execute("UPDATE alice.detect_files SET rehashed_at = $2 WHERE path = $1", path, now)
    async with det.pool.acquire() as con:
        progress = await _cycle_progress(con, ok, started)
    logger.info("Re-hash portion: %d files (%d bytes) hashed, %d differing, %d unreadable, %d vanished; cycle %s %%",
                hashed, hashed_bytes, len(mismatches), len(unreadable), len(vanished), progress["percent"])
    return {"hashed": hashed, "bytes": hashed_bytes, "budget_bytes": budget, "mismatches": mismatches,
            "unreadable": unreadable, "vanished": vanished, "cycle": progress,
            "skipped_folders": stats.skipped_folders}


async def apply(det: Detector, paths: list[str]) -> dict:
    """Differing hashes → like an original changed in place (AK-25, EC-9)."""
    stats = Stats("reconcile")
    results = []
    async with exclusive(det):
        for path in paths:
            async with det.pool.acquire() as con:
                row = await con.fetchrow("SELECT path, source_id, folder, size, mtime_ns FROM alice.detect_files "
                                         "WHERE path = $1", path)
            st = await asyncio.to_thread(fsscan.file_stat, path)
            if row is None or st is None:
                results.append({"path": path, "applied": False, "detail": "Datei nicht mehr vorhanden"})
                continue
            before = stats.changed_in_place
            await det.check_known(path, dict(row), row["folder"], st[0], st[1], stats)
            async with det.pool.acquire() as con:
                now_sid = await con.fetchval("UPDATE alice.detect_files SET rehashed_at = NOW() WHERE path = $1 "
                                             "RETURNING source_id", path)
            results.append({"path": path, "applied": stats.changed_in_place > before,
                            "source_id": row["source_id"], "new_source_id": now_sid})
    return {"results": results, "newly_deleted": stats.newly_deleted}
