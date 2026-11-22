"""
Core of alice-file-detection (PROJ-116).

- Day scan: only new material. Directories are re-listed only when their mtime
  changed (or the change is not yet confirmed by a second scan); only paths that
  are not known are hashed, and only after size + mtime stayed the same between
  two scans. Never removes anything.
- Nightly run: full listing of all active folders. New files, originals changed
  in place, disappeared locations (with the safeguards against mass deletion)
  and a stored summary.

The register (alice-source-registry) is the truth about sources and locations;
alice.detect_* only mirrors what this service has seen. Losing a mirror row is
harmless: the path is hashed again and the register maps it by hash.
Originals are only ever opened for reading.
"""
from __future__ import annotations

import asyncio
import json
import logging
import posixpath
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import fsscan
from .config import Settings
from .registry import RegistryClient, RegistryError, RegistryUnavailable

logger = logging.getLogger("alice-file-detection")

PROGRESS_EVERY = 100
PROBLEM_LIST_LIMIT = 1000


class Busy(Exception):
    """Another run is active (AK-26)."""


@dataclass
class Folder:
    id: int
    path: str
    enabled: bool


@dataclass
class Stats:
    kind: str
    started: float = field(default_factory=time.monotonic)
    files_scanned: int = 0
    dirs_scanned: int = 0
    dirs_listed: int = 0
    hashed: int = 0
    new_sources: int = 0
    new_locations: int = 0
    removed_locations: int = 0
    newly_deleted: int = 0
    reactivated: int = 0
    changed_in_place: int = 0
    registered_batch: int = 0
    unsupported: dict = field(default_factory=lambda: defaultdict(Counter))
    skipped_folders: list = field(default_factory=list)
    blocked_shares: list = field(default_factory=list)
    removed_folders: dict = field(default_factory=lambda: defaultdict(int))

    def summary(self, problems: list[dict], problem_count: int) -> dict:
        total = Counter()
        for c in self.unsupported.values():
            total.update(c)
        return {
            "kind": self.kind,
            "duration_seconds": round(time.monotonic() - self.started, 1),
            "files_scanned": self.files_scanned,
            "dirs_scanned": self.dirs_scanned,
            "dirs_listed": self.dirs_listed,
            "hashed": self.hashed,
            "new_sources": self.new_sources,
            "new_locations": self.new_locations,
            "removed_locations": self.removed_locations,
            "newly_deleted": self.newly_deleted,
            "reactivated": self.reactivated,
            "changed_in_place": self.changed_in_place,
            "unsupported_extensions": {
                "per_folder": {f: dict(sorted(c.items())) for f, c in sorted(self.unsupported.items()) if c},
                "total": dict(sorted(total.items())),
            },
            "skipped_folders": self.skipped_folders,
            "blocked_shares": self.blocked_shares,
            "removed_folders": [{"folder": f, "removed_locations": n} for f, n in sorted(self.removed_folders.items())],
            "problems": {"count": problem_count, "items": problems},
        }


def _modified(mtime_ns: int) -> datetime:
    return datetime.fromtimestamp(mtime_ns / 1e9, tz=timezone.utc)


def _norm_folder(path: str) -> str:
    return path.rstrip("/") or "/"


class Detector:
    def __init__(self, settings: Settings, pool, registry: RegistryClient):
        self.s = settings
        self.pool = pool
        self.registry = registry
        self.running: str | None = None  # kind of the active run
        self.task: asyncio.Task | None = None
        self.warnings: dict[str, str] = {}  # folder → reason it was skipped (health, AK-22)
        self.paused_reason: str | None = None  # register not reachable (AK-25)
        self.last_day_start = float("-inf")
        self.last_night_attempt = float("-inf")
        self.last_tick = time.monotonic()

    # ================================================================ runs
    def start(self, kind: str, trigger: str = "schedule") -> asyncio.Task:
        """Start a run now; Busy if one is active (never two in parallel, AK-26/30)."""
        if self.running:
            raise Busy(self.running)
        self.running = kind
        if kind == "day":
            self.last_day_start = time.monotonic()
        else:
            self.last_night_attempt = time.monotonic()
        self.task = asyncio.create_task(self._run(kind, trigger))
        return self.task

    async def _run(self, kind: str, trigger: str) -> dict:
        stats = Stats(kind)
        state, error, summary = "done", None, None
        try:
            async with self.pool.acquire() as con:
                run_id = await con.fetchval("INSERT INTO alice.detect_runs (kind, trigger) VALUES ($1, $2) RETURNING id",
                                            kind, trigger)
            logger.info("%s run %s started (%s)", "Nightly" if kind == "night" else "Day", run_id, trigger)
            try:
                if kind == "day":
                    await self.day_scan(stats)
                else:
                    await self.nightly(stats)
                if self.paused_reason:
                    logger.info("Register reachable again, detection continues")
                self.paused_reason = None
            except RegistryUnavailable as exc:
                state, error = "paused", str(exc)
                self.paused_reason = str(exc)
                logger.warning("Register not reachable, run paused, retrying next interval: %s", exc)
            except Exception as exc:
                state, error = "failed", f"{exc.__class__.__name__}: {exc}"
                logger.exception("%s run failed", kind)
            problems, count = await self.problems(PROBLEM_LIST_LIMIT)
            summary = stats.summary(problems, count)
            async with self.pool.acquire() as con:
                await con.execute("UPDATE alice.detect_runs SET state = $2, finished_at = NOW(), error = $3, "
                                  "summary = $4::jsonb WHERE id = $1", run_id, state, error,
                                  json.dumps(summary, default=str))
                if kind == "night":
                    await con.execute("DELETE FROM alice.detect_runs WHERE started_at < NOW() - make_interval(days => $1)",
                                      self.s.retention_days)
            if kind == "night":
                logger.info("Nightly run %s %s, summary: %s", run_id, state, json.dumps(summary, default=str))
            else:
                logger.info("Day run %s %s: %d new sources, %d new locations, %d dirs listed, %d hashed",
                            run_id, state, stats.new_sources, stats.new_locations, stats.dirs_listed, stats.hashed)
            return {"id": run_id, "state": state, "error": error, "summary": summary}
        finally:
            self.running = None

    async def mark_aborted(self) -> int:
        """Runs still 'running' after a restart were interrupted."""
        async with self.pool.acquire() as con:
            res = await con.execute("UPDATE alice.detect_runs SET state = 'aborted', finished_at = NOW(), "
                                    "error = 'Dienst während des Laufs neu gestartet' WHERE state = 'running'")
        return int(res.split()[-1])

    # ================================================================ schedule
    def nightly_slot(self, now: datetime) -> datetime:
        """Most recent scheduled nightly time (aware, UTC)."""
        local = now.astimezone(self.s.tz)
        slot = datetime.combine(local.date(), self.s.nightly, tzinfo=self.s.tz)
        if slot > local:
            slot = datetime.combine(local.date() - timedelta(days=1), self.s.nightly, tzinfo=self.s.tz)
        return slot.astimezone(timezone.utc)

    async def nightly_due(self, now: datetime | None = None) -> str | None:
        """'schedule' / 'catchup' if the nightly run of the last slot is still to do (AK-27), else None."""
        now = now or datetime.now(timezone.utc)
        slot = self.nightly_slot(now)
        if now - slot > timedelta(hours=self.s.catchup_hours):
            return None  # too late: the next nightly run takes over
        async with self.pool.acquire() as con:
            states = [r["state"] for r in await con.fetch(
                "SELECT state FROM alice.detect_runs WHERE kind = 'night' AND started_at >= $1", slot)]
        if "done" in states:
            return None
        return "catchup" if states else "schedule"

    async def tick(self) -> None:
        self.last_tick = time.monotonic()
        if self.running:
            return
        interval = self.s.scan_interval_seconds
        reason = await self.nightly_due()
        if reason and time.monotonic() - self.last_night_attempt >= min(interval, 600):
            self.start("night", reason)
        elif time.monotonic() - self.last_day_start >= interval:
            self.start("day", "schedule")

    # ================================================================ folders
    async def folders(self) -> list[Folder]:
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT id, path, enabled FROM alice.dms_watched_folders ORDER BY path LIMIT 10000")
        return [Folder(r["id"], _norm_folder(r["path"]), r["enabled"]) for r in rows]

    def excluded(self, path: str) -> bool:
        return any(fsscan.under(path, p) for p in self.s.exclude_paths)

    async def check_folder(self, folder: str, stats: Stats) -> bool:
        """Unreadable, or empty although files below it are known (mount missing) → skip (AK-22)."""
        readable, empty, err = await asyncio.to_thread(fsscan.folder_state, folder)
        reason = None
        if not readable:
            reason = f"nicht lesbar ({err})"
        elif empty:
            async with self.pool.acquire() as con:
                known = await con.fetchval("SELECT EXISTS (SELECT 1 FROM alice.detect_files WHERE folder = $1)", folder)
            if known:
                reason = "leer, obwohl Dateien darunter bekannt sind (Freigabe nicht eingehängt?)"
        if reason:
            if self.warnings.get(folder) != reason:
                logger.warning("Watched folder %s skipped: %s", folder, reason)
            self.warnings[folder] = reason
            stats.skipped_folders.append({"folder": folder, "reason": reason})
            return False
        if folder in self.warnings:
            logger.info("Watched folder %s reachable again", folder)
            self.warnings.pop(folder, None)
        return True

    def _skip_subdir(self, entry: fsscan.Entry, folder: str, folder_paths: set[str]) -> bool:
        return (fsscan.skip_dir(entry.name, self.s) or (entry.path in folder_paths and entry.path != folder)
                or self.excluded(entry.path))

    # ================================================================ state helpers
    async def _problem(self, path: str, folder: str, cause: str) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO alice.detect_problems (path, folder, cause) VALUES ($1, $2, $3) "
                "ON CONFLICT (path) DO UPDATE SET cause = EXCLUDED.cause, folder = EXCLUDED.folder, last_seen = NOW()",
                path, folder, cause[:2000])
        logger.warning("Detection problem %s: %s", path, cause)

    async def _clear(self, path: str, pending: bool = True) -> None:
        async with self.pool.acquire() as con:
            await con.execute("DELETE FROM alice.detect_problems WHERE path = $1", path)
            if pending:
                await con.execute("DELETE FROM alice.detect_pending WHERE path = $1", path)

    async def _set_pending(self, path: str, folder: str, size: int, mtime_ns: int) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO alice.detect_pending (path, folder, size, mtime_ns) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (path) DO UPDATE SET folder = EXCLUDED.folder, size = EXCLUDED.size, "
                "mtime_ns = EXCLUDED.mtime_ns, last_seen = NOW()", path, folder, size, mtime_ns)

    async def _set_file(self, path: str, source_id: str, folder: str, size: int, mtime_ns: int) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO alice.detect_files (path, source_id, folder, size, mtime_ns) VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (path) DO UPDATE SET source_id = EXCLUDED.source_id, folder = EXCLUDED.folder, "
                "size = EXCLUDED.size, mtime_ns = EXCLUDED.mtime_ns, last_seen = NOW()",
                path, source_id, folder, size, mtime_ns)

    async def problems(self, limit: int = 500) -> tuple[list[dict], int]:
        async with self.pool.acquire() as con:
            count = await con.fetchval("SELECT count(*) FROM alice.detect_problems")
            rows = await con.fetch("SELECT path, folder, cause, first_seen, last_seen FROM alice.detect_problems "
                                   "ORDER BY path LIMIT $1", limit)
        return [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in dict(r).items()} for r in rows], count

    # ================================================================ one file
    async def _hash(self, path: str, folder: str, stats: Stats) -> str | None:
        """sha256 of the original; None if it vanished (EC-1) or cannot be read (problem, AK-24)."""
        try:
            h = await asyncio.to_thread(fsscan.sha256_file, path)
        except FileNotFoundError:
            await self._clear(path)
            return None
        except OSError as exc:
            await self._problem(path, folder, fsscan.problem_cause(exc))
            return None
        stats.hashed += 1
        return h

    def _count_registration(self, r: dict, stats: Stats) -> None:
        if r.get("created"):
            stats.new_sources += 1
        else:
            stats.new_locations += 1
        if r.get("reactivated"):
            stats.reactivated += 1

    async def take_new(self, path: str, folder: str, size: int, mtime_ns: int, stats: Stats,
                       batch: bool = False) -> bool:
        """Hash a stable new file and register it. True if registered."""
        kind = fsscan.kind_of(posixpath.basename(path), self.s)
        if kind is None:
            return False
        h = await self._hash(path, folder, stats)
        if h is None:
            if await asyncio.to_thread(fsscan.file_stat, path):  # unreadable: keep waiting, retried every scan
                await self._set_pending(path, folder, size, mtime_ns)
            return False
        after = await asyncio.to_thread(fsscan.file_stat, path)
        if after is None:
            await self._clear(path)
            return False
        if after != (size, mtime_ns):  # still being written: wait for the next scan (AK-2)
            await self._set_pending(path, folder, *after)
            return False
        try:
            r = await self.registry.register(kind=kind, hash=h, title=posixpath.basename(path), path=path, size=size,
                                             modified=_modified(mtime_ns), batch=batch)
        except RegistryError as exc:
            await self._problem(path, folder, f"Register lehnt ab: {exc}")
            return False
        self._count_registration(r, stats)
        if batch:
            stats.registered_batch += 1
        await self._set_file(path, r["id"], folder, size, mtime_ns)
        await self._clear(path)
        return True

    async def check_known(self, path: str, row: dict, folder: str, size: int, mtime_ns: int, stats: Stats) -> None:
        """Known path with other size or mtime: original changed in place (AK-16–18)."""
        h = await self._hash(path, folder, stats)
        if h is None:
            return
        if await asyncio.to_thread(fsscan.file_stat, path) != (size, mtime_ns):
            return  # changed while hashing: next run
        try:
            src = await self.registry.get_source(row["source_id"])
            if src is None or h == src["hash"]:
                if src is None:  # register lost the source: treat the path as new
                    await self.take_new(path, folder, size, mtime_ns, stats)
                else:
                    await self._set_file(path, src["id"], folder, size, mtime_ns)
                    await self._clear(path, pending=False)
                return
            others = [loc for loc in src["locations"] if loc.get("present") and loc.get("path") != path]
            owner = await self.registry.by_hash(h)
            stats.changed_in_place += 1
            if not others and owner is None:
                # only location, new content: same source, stages from extract on run again
                await self.registry.update_original(src["id"], hash=h, size=size, modified=_modified(mtime_ns))
                await self._set_file(path, src["id"], folder, size, mtime_ns)
                logger.info("Original %s changed in place: source %s updated", path, src["id"])
            else:
                # old content lives on elsewhere, or the new content is already known:
                # the path becomes a location of the new content, the old source loses it
                kind = fsscan.kind_of(posixpath.basename(path), self.s) or src["kind"]
                r = await self.registry.register(kind=kind, hash=h, title=posixpath.basename(path), path=path,
                                                 size=size, modified=_modified(mtime_ns))
                self._count_registration(r, stats)
                await self._set_file(path, r["id"], folder, size, mtime_ns)
                g = await self.registry.gone(src["id"], path)
                if g and g.get("deleted"):
                    stats.newly_deleted += 1
                logger.info("Original %s changed in place: now source %s (was %s)", path, r["id"], src["id"])
            await self._clear(path, pending=False)
        except RegistryError as exc:
            await self._problem(path, folder, f"Register lehnt ab: {exc}")

    # ================================================================ day scan
    async def day_scan(self, stats: Stats) -> None:
        folders = await self.folders()
        folder_paths = {f.path for f in folders}
        by_path = {f.path: f for f in folders}
        async with self.pool.acquire() as con:
            known = {r["path"]: dict(r) for r in await con.fetch(
                "SELECT path, source_id, folder, size, mtime_ns FROM alice.detect_files")}
            pending = {r["path"]: dict(r) for r in await con.fetch(
                "SELECT path, folder, size, mtime_ns FROM alice.detect_pending")}
        handled: set[str] = set()
        dir_updates: list[tuple] = []
        dir_deletes: list[str] = []

        for folder in [f for f in folders if f.enabled]:
            if self.excluded(folder.path) or not await self.check_folder(folder.path, stats):
                continue
            async with self.pool.acquire() as con:
                rows = await con.fetch("SELECT path, parent, mtime_ns, confirmed FROM alice.detect_dirs WHERE folder = $1",
                                       folder.path)
            dirs = {r["path"]: dict(r) for r in rows}
            children: dict[str, list[str]] = defaultdict(list)
            for r in rows:
                if r["parent"]:
                    children[r["parent"]].append(r["path"])
            seen_dirs: set[str] = set()
            queue: list[tuple[str, str | None]] = [(folder.path, None)]
            while queue:
                d, parent = queue.pop()
                if d in seen_dirs:
                    continue
                mtime = await asyncio.to_thread(fsscan.dir_mtime, d)
                if mtime is None:
                    continue
                seen_dirs.add(d)
                stats.dirs_scanned += 1
                old = dirs.get(d)
                if old and old["mtime_ns"] == mtime and old["confirmed"]:
                    queue.extend((c, d) for c in children.get(d, [])
                                 if c not in seen_dirs and c not in folder_paths and not self.excluded(c))
                    continue
                try:
                    entries = await asyncio.to_thread(fsscan.list_dir, d)
                except OSError as exc:
                    await self._problem(d, folder.path, f"Ordner: {fsscan.problem_cause(exc)}")
                    seen_dirs.discard(d)
                    continue
                stats.dirs_listed += 1
                for e in entries:
                    if e.is_dir:
                        if not self._skip_subdir(e, folder.path, folder_paths):
                            queue.append((e.path, d))
                        continue
                    if fsscan.skip_file(e.name, self.s) or e.size == 0 or e.path in known:
                        continue
                    if fsscan.kind_of(e.name, self.s) is None:
                        continue
                    stats.files_scanned += 1
                    handled.add(e.path)
                    p = pending.get(e.path)
                    if p and (p["size"], p["mtime_ns"]) == (e.size, e.mtime_ns):
                        await self.take_new(e.path, folder.path, e.size, e.mtime_ns, stats)
                    else:
                        await self._set_pending(e.path, folder.path, e.size, e.mtime_ns)
                # a change is confirmed by the next scan seeing the same mtime (files added in the
                # same instant as the listing would otherwise be missed on coarse NAS timestamps)
                dir_updates.append((d, folder.path, parent, mtime, bool(old and old["mtime_ns"] == mtime)))
            dir_deletes.extend(p for p in dirs if p not in seen_dirs)

        # waiting files whose folder was not listed again: check them directly (AK-2)
        for path, p in pending.items():
            if path in handled:
                continue
            f = by_path.get(p["folder"])
            if f is None:
                await self._clear(path)
                continue
            if not f.enabled or f.path in self.warnings:
                continue
            st = await asyncio.to_thread(fsscan.file_stat, path)
            if st is None:
                await self._clear(path)
            elif path in known:
                await self._clear(path)
            elif st == (p["size"], p["mtime_ns"]):
                await self.take_new(path, f.path, *st, stats)
            else:
                await self._set_pending(path, f.path, *st)

        await self._retry_known_problems(known, by_path, stats)

        async with self.pool.acquire() as con, con.transaction():
            if dir_deletes:
                await con.execute("DELETE FROM alice.detect_dirs WHERE path = ANY($1::text[])", dir_deletes)
            await con.executemany(
                "INSERT INTO alice.detect_dirs (path, folder, parent, mtime_ns, confirmed) VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (path) DO UPDATE SET folder = EXCLUDED.folder, parent = EXCLUDED.parent, "
                "mtime_ns = EXCLUDED.mtime_ns, confirmed = EXCLUDED.confirmed, updated_at = NOW()", dir_updates)

    async def _retry_known_problems(self, known: dict, by_path: dict, stats: Stats) -> None:
        """Problems of known paths (in-place change not readable) are retried by every scan."""
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT path FROM alice.detect_problems LIMIT 10000")
        for r in rows:
            path = r["path"]
            st = await asyncio.to_thread(fsscan.file_stat, path)
            if st is None:
                if await asyncio.to_thread(fsscan.dir_mtime, path) is None:
                    await self._clear(path, pending=False)  # gone: entry disappears
                else:  # unreadable folder: entry disappears once it can be listed
                    try:
                        await asyncio.to_thread(fsscan.list_dir, path)
                        await self._clear(path, pending=False)
                    except OSError:
                        pass
                continue
            row = known.get(path)
            if row is None:
                continue  # new file: retried through the waiting files
            f = by_path.get(row["folder"])
            if f and f.enabled and f.path not in self.warnings:
                await self.check_known(path, row, f.path, *st, stats)

    # ================================================================ nightly run
    async def _walk(self, folder: str, folder_paths: set[str], stats: Stats, unreadable: list[str]):
        """All regular files below a watched folder (full listing)."""
        stack = [folder]
        while stack:
            d = stack.pop()
            try:
                entries = await asyncio.to_thread(fsscan.list_dir, d)
            except OSError as exc:
                if d != folder:
                    await self._problem(d, folder, f"Ordner: {fsscan.problem_cause(exc)}")
                unreadable.append(d)
                continue
            stats.dirs_scanned += 1
            stats.dirs_listed += 1
            for e in entries:
                if e.is_dir:
                    if not self._skip_subdir(e, folder, folder_paths):
                        stack.append(e.path)
                elif not fsscan.skip_file(e.name, self.s) and e.size > 0:
                    yield e

    async def nightly(self, stats: Stats) -> None:
        folders = await self.folders()
        folder_paths = {f.path for f in folders}
        async with self.pool.acquire() as con:
            known = {r["path"]: dict(r) for r in await con.fetch(
                "SELECT path, source_id, folder, size, mtime_ns FROM alice.detect_files")}
            pending = {r["path"]: (r["size"], r["mtime_ns"]) for r in await con.fetch(
                "SELECT path, size, mtime_ns FROM alice.detect_pending")}
        snapshot = {p: dict(r) for p, r in known.items()}
        seen: set[str] = set()
        walked: set[str] = set()
        protected: list[str] = []  # nothing is removed below these (disabled, skipped, unreadable)
        new_count = 0

        for folder in folders:
            if not folder.enabled:
                protected.append(folder.path)
                continue
            if self.excluded(folder.path) or not await self.check_folder(folder.path, stats):
                protected.append(folder.path)
                continue
            unreadable: list[str] = []
            async for e in self._walk(folder.path, folder_paths, stats, unreadable):
                stats.files_scanned += 1
                if fsscan.kind_of(e.name, self.s) is None:
                    stats.unsupported[folder.path][fsscan.extension(e.name) or "(ohne)"] += 1
                    continue
                seen.add(e.path)
                row = known.get(e.path)
                if row is not None:
                    if row["folder"] != folder.path:  # nested folder added: longest match wins (AK-21)
                        async with self.pool.acquire() as con:
                            await con.execute("UPDATE alice.detect_files SET folder = $2 WHERE path = $1",
                                              e.path, folder.path)
                        row["folder"] = folder.path
                        snapshot[e.path]["folder"] = folder.path
                    if (row["size"], row["mtime_ns"]) != (e.size, e.mtime_ns):
                        await self.check_known(e.path, row, folder.path, e.size, e.mtime_ns, stats)
                    continue
                # new path: stable if unchanged between listing and the end of hashing
                if await self.take_new(e.path, folder.path, e.size, e.mtime_ns, stats, batch=True):
                    new_count += 1
                    if new_count % PROGRESS_EVERY == 0:
                        logger.info("Nightly run: %d new files registered so far (%d files scanned)",
                                    new_count, stats.files_scanned)
                pending.pop(e.path, None)
            protected.extend(unreadable)
            walked.add(folder.path)
            for path in [p for p in pending if fsscan.under(p, folder.path)]:
                if path not in seen:  # waiting file vanished
                    await self._clear(path)
                    pending.pop(path, None)

        if stats.registered_batch:
            await self.registry.flush()
        if new_count:
            logger.info("Nightly run: %d new files registered", new_count)
        await self._remove_missing(snapshot, seen, folder_paths, walked, protected, stats)
        await self._retry_known_problems({}, {}, stats)  # only drops entries of vanished paths

    async def _remove_missing(self, snapshot: dict, seen: set[str], folder_paths: set[str], walked: set[str],
                              protected: list[str], stats: Stats) -> None:
        """Disappeared locations → register; with the deletion limit per share (AK-10, AK-20, AK-23)."""
        known_per_share: Counter = Counter()
        missing: dict[str, list[dict]] = defaultdict(list)
        removed_folder_rows: list[dict] = []
        for path, row in snapshot.items():
            share = fsscan.share_of(path, self.s.nas_root, row["folder"])
            known_per_share[share] += 1
            if path in seen:
                continue
            if any(fsscan.under(path, p) for p in protected):
                continue  # below a disabled, skipped or unreadable folder: never remove (AK-19, AK-22)
            if row["folder"] not in folder_paths:
                removed_folder_rows.append(row)
                continue
            if row["folder"] not in walked:
                continue
            missing[share].append(row)

        # folders deleted from the list: no limit, deliberate admin action (AK-20, EC-6)
        for row in removed_folder_rows:
            if await self._remove(row, stats):
                stats.removed_folders[row["folder"]] += 1
        for share, rows in sorted(missing.items()):
            known_n = known_per_share[share]
            percent = 100.0 * len(rows) / known_n if known_n else 100.0
            if percent > self.s.delete_limit_percent:
                stats.blocked_shares.append({"share": share, "known": known_n, "missing": len(rows),
                                             "percent": round(percent, 1)})
                logger.warning("Share %s: %d of %d known locations missing (%.1f %% > %s %%), nothing removed",
                               share, len(rows), known_n, percent, self.s.delete_limit_percent)
                continue
            for row in rows:
                await self._remove(row, stats)

    async def _remove(self, row: dict, stats: Stats) -> bool:
        try:
            g = await self.registry.gone(row["source_id"], row["path"])
        except RegistryError as exc:
            await self._problem(row["path"], row["folder"], f"Register lehnt Entfernen ab: {exc}")
            return False
        async with self.pool.acquire() as con:
            await con.execute("DELETE FROM alice.detect_files WHERE path = $1", row["path"])
        stats.removed_locations += 1
        if g and g.get("deleted"):
            stats.newly_deleted += 1
        return True
