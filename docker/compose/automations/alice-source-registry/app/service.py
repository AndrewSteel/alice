"""
Core of alice-source-registry: keeps the source register (PostgreSQL) and the
source-of-truth repo (git) consistent.

- All repo operations run under one asyncio lock and in a worker thread, so git
  operations are serialized and each commit only contains its own paths.
- For every source the register stores the git blob id of the content the
  pipeline wrote or accepted last. Any other content (foreign commit or
  uncommitted edit) is a hand correction.
- PostgreSQL is the truth about stage states; Redis is only the work queue.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from datetime import datetime, timezone

from . import markdown as md
from .config import Settings
from .gitrepo import HAND, PIPELINE, GitError, GitRepo, RepoBusy, RepoForeign, RepoUnavailable
from .workqueue import WorkQueue

logger = logging.getLogger("alice-source-registry")

BACKOFF_SECONDS = [60, 300, 1800, 7200, 43200]  # 1 min, 5 min, 30 min, 2 h, 12 h
MAX_ATTEMPTS = 5
QUEUE_RESYNC_SECONDS = 600
ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
ID_LENGTH = 12
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
PROTECTED_FIELDS = set(md.REGISTER_FIELDS) | {"manual"}
SOURCE_COLS = ("id, kind, hash, size, modified, captured, title, path, blob, repo_error, repo_error_at, "
               "deleted, deleted_at, created_at, updated_at")


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Locked(Conflict):
    """The markdown is locked by an invalid hand edit (AK-28)."""


class Invalid(Exception):
    pass


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _loc_fm(row) -> dict:
    if row["path"] is not None:
        return {"path": row["path"]}
    loc = {"mailbox": row["mailbox"]}
    # PROJ-123: folder + UID of a mail location (older mail locations have neither)
    if row["folder"] is not None:
        loc["folder"] = row["folder"]
    if row["uid"] is not None:
        loc["uid"] = row["uid"]
    loc["message_id"] = row["message_id"]
    return loc


def _discarded(src: dict) -> dict:
    return {"id": src["id"], "path": src["path"], "changed": False, "commit": None, "reset": [], "discarded": True}


class Registry:
    def __init__(self, settings: Settings, pool, redis_client=None):
        self.s = settings
        self.pool = pool
        self.repo = GitRepo(settings.repo_path, settings.git_lock_stale_seconds)
        self.queue = WorkQueue(redis_client)
        self.lock = asyncio.Lock()
        self.opened = False
        self.available = False
        self.unavailable_reason = "Repo-Ordner noch nicht geprüft"
        self.batches: dict[str, dict] = {}  # stage -> {"ids": {source_id: {paths}}, "since": monotonic}
        self.warned: set[str] = set()
        self.served: set[tuple[str, str]] = set()  # (stage, kind) known as served (PROJ-120)
        self.force_scan = True
        self.last_scan = 0.0
        self.last_resync = 0.0
        self.last_tick = time.monotonic()

    # ================================================================ repo access
    def _set_available(self, ok: bool, reason: str = "") -> None:
        if ok and not self.available:
            logger.info("Source-of-truth repo available: %s", self.repo.path)
            self.force_scan = True  # catch hand corrections made while it was away (AK-31)
        elif not ok and (self.available or reason != self.unavailable_reason):
            logger.warning("Source-of-truth repo unavailable, processing paused: %s", reason)
        self.available, self.unavailable_reason = ok, ("" if ok else reason)

    async def _io(self, fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except RepoBusy:
            raise
        except RepoUnavailable as exc:
            self._set_available(False, str(exc))
            raise
        except OSError as exc:
            self._set_available(False, f"Zugriff auf den Repo-Ordner fehlgeschlagen: {exc}")
            raise RepoUnavailable(str(exc)) from exc

    def require_available(self) -> None:
        if not self.available:
            raise RepoUnavailable(self.unavailable_reason)

    async def startup(self) -> None:
        """Init or open the repo. RepoForeign propagates: the service must not start (AK-3)."""
        try:
            result = await asyncio.to_thread(self.repo.init_or_open)
            self.opened = True
            logger.info("Source-of-truth repo %s (%s)", result, self.repo.path)
        except RepoUnavailable as exc:
            self._set_available(False, str(exc))
            return
        await self.check_repo()

    async def check_repo(self) -> None:
        try:
            if not self.opened:
                await asyncio.wait_for(asyncio.to_thread(self.repo.init_or_open), 60)
                self.opened = True
            ok, reason = await asyncio.wait_for(asyncio.to_thread(self.repo.available), 15)
        except RepoForeign as exc:
            ok, reason = False, str(exc)
        except (RepoUnavailable, OSError) as exc:
            ok, reason = False, str(exc)
        except asyncio.TimeoutError:
            ok, reason = False, "Zeitüberschreitung beim Zugriff auf den Repo-Ordner"
        self._set_available(ok, reason)

    # ================================================================ db helpers
    async def _source(self, con, source_id: str, lock: bool = False) -> dict:
        row = await con.fetchrow(f"SELECT {SOURCE_COLS} FROM alice.sources WHERE id = $1"
                                 + (" FOR UPDATE" if lock else ""), source_id)
        if not row:
            raise NotFound(f"Quelle {source_id} nicht gefunden")
        return dict(row)

    async def _present_locations(self, con, source_id: str) -> list[dict]:
        rows = await con.fetch(
            "SELECT path, mailbox, folder, uid, message_id FROM alice.source_locations "
            "WHERE source_id = $1 AND present ORDER BY first_seen, id", source_id)
        return [_loc_fm(r) for r in rows]

    async def _parents(self, con, source_id: str) -> list[str]:
        rows = await con.fetch("SELECT parent_id FROM alice.source_parents WHERE source_id = $1 "
                               "ORDER BY created_at, parent_id", source_id)
        return [r["parent_id"] for r in rows]

    async def _event(self, con, source_id: str | None, level: str, event: str, message: str) -> None:
        await con.execute("INSERT INTO alice.source_events (source_id, level, event, message) VALUES ($1, $2, $3, $4)",
                          source_id, level, event, message[:4000])

    async def _stage_names(self, con) -> list[str]:
        return [r["name"] for r in await con.fetch("SELECT name FROM alice.pipeline_stages ORDER BY position, name")]

    async def _require_stage(self, con, stage: str) -> None:
        if not await con.fetchval("SELECT 1 FROM alice.pipeline_stages WHERE name = $1", stage):
            raise NotFound(f"Stufe {stage} unbekannt")

    async def _reset_dependents(self, con, source_id: str, exclude: str | None, changed,
                                meta=(), keep=()) -> list[str]:
        """The markdown changed: stages flagged resets_on_content_change (any change, AK-20) and stages
        whose resets_on_fields name a changed field or `content` (PROJ-118) → pending.
        `meta` (PROJ-119): changed register fields (`locations`, `deleted`) that only reset stages
        naming them in resets_on_fields, not every resets_on_content_change stage.
        `keep` (PROJ-124): stages this write never resets (e.g. classify of a mail whose attachment links
        were added)."""
        changed = sorted({str(c) for c in changed})
        meta = sorted({str(c) for c in meta})
        if not changed and not meta:
            return []
        rows = await con.fetch(
            """
            UPDATE alice.source_stages ss
               SET state = 'pending', attempts = 0, last_error = NULL, next_retry_at = NULL,
                   claim_token = NULL, started_at = NULL, rebuild_run = NULL
              FROM alice.pipeline_stages ps
             WHERE ps.name = ss.stage
               AND ((ps.resets_on_content_change AND cardinality($3::text[]) > 0)
                    OR ps.resets_on_fields && ($3::text[] || $4::text[]))
               AND ss.source_id = $1 AND ss.state NOT IN ('skipped', 'pending')
               AND ss.stage IS DISTINCT FROM $2 AND NOT (ss.stage = ANY($5::text[]))
            RETURNING ss.stage
            """, source_id, exclude, changed, meta, list(keep))
        stages = [r["stage"] for r in rows]
        now = time.time()
        for stage in stages:
            await self.queue.push(stage, {source_id: now})
        return stages

    async def _register_fields(self, con, src: dict) -> dict:
        return {
            "id": src["id"], "schema": md.SCHEMA_VERSION, "kind": src["kind"],
            "locations": await self._present_locations(con, src["id"]),
            "parents": await self._parents(con, src["id"]),
            "hash": src["hash"], "size": src["size"], "modified": _iso(src["modified"]),
            "captured": _iso(src["captured"]),
            "deleted": _iso(src["deleted_at"]) if src["deleted"] else None,
        }

    async def _reset_after(self, con, source_id: str, stage: str) -> list[str]:
        """All stages after `stage` (by position, not skipped) → pending (PROJ-116: original changed in place)."""
        rows = await con.fetch(
            """
            UPDATE alice.source_stages ss
               SET state = 'pending', attempts = 0, last_error = NULL, next_retry_at = NULL,
                   claim_token = NULL, started_at = NULL, rebuild_run = NULL
              FROM alice.pipeline_stages ps
             WHERE ps.name = ss.stage AND ss.source_id = $1 AND ss.state NOT IN ('skipped', 'pending')
               AND ps.position > (SELECT position FROM alice.pipeline_stages WHERE name = $2)
            RETURNING ss.stage
            """, source_id, stage)
        stages = [r["stage"] for r in rows]
        now = time.time()
        for st in stages:
            await self.queue.push(st, {source_id: now})
        return stages

    # ================================================================ batches (AK-8)
    def _batch_ids(self) -> set[str]:
        return {sid for b in self.batches.values() for sid in b["ids"]}

    def _batch_paths(self) -> set[str]:
        return {p for b in self.batches.values() for paths in b["ids"].values() for p in paths}

    def _add_to_batch(self, stage: str, source_id: str, paths) -> int:
        batch = self.batches.setdefault(stage, {"ids": {}, "since": time.monotonic()})
        batch["ids"].setdefault(source_id, set()).update(p for p in paths if p)
        return len(batch["ids"])

    async def _flush_stage(self, stage: str) -> str | None:
        batch = self.batches.pop(stage, None)
        if not batch or not batch["ids"]:
            return None
        paths = {p for ps in batch["ids"].values() for p in ps}
        try:
            return await self._io(self.repo.commit, paths, f"rebuild: {stage} {len(batch['ids'])} sources", PIPELINE)
        except Exception:
            # keep the batch; the files are written and matched by their blob ids
            old = self.batches.setdefault(stage, {"ids": {}, "since": batch["since"]})
            for sid, ps in batch["ids"].items():
                old["ids"].setdefault(sid, set()).update(ps)
            raise

    async def _flush_containing(self, source_id: str, keep_stage: str | None = None) -> None:
        for stage in [s for s, b in self.batches.items() if source_id in b["ids"] and s != keep_stage]:
            await self._flush_stage(stage)

    async def flush_due(self, force: bool = False) -> int:
        """Commit batches that reached the file limit or the time limit."""
        flushed = 0
        async with self.lock:
            now = time.monotonic()
            for stage in list(self.batches):
                b = self.batches[stage]
                if force or len(b["ids"]) >= self.s.batch_max_files or now - b["since"] >= self.s.batch_max_seconds:
                    if await self._flush_stage(stage):
                        flushed += 1
        return flushed

    # ================================================================ writing markdown
    async def _claim_valid(self, con, src: dict, stage: str, token: str) -> bool:
        """The writing stage still holds its claim and the source is not deleted (PROJ-118, EC-15)."""
        if src["deleted"]:
            return False
        return bool(await con.fetchval(
            "SELECT 1 FROM alice.source_stages WHERE source_id = $1 AND stage = $2 AND state = 'running' "
            "AND claim_token = $3::uuid", src["id"], stage, token))

    async def _write_source(self, con, src: dict, *, label: str, stage: str | None = None,
                            fields: dict | None = None, content: str | None = None, batch: bool = False,
                            token: str | None = None, keep_stages=()) -> dict:
        """Write the source markdown from register + stage values, respecting `manual`.
        Caller holds self.lock and a transaction with the source row locked.
        With `token` the result is discarded (nothing written) if the claim of `stage` was taken back
        meanwhile, e.g. by a hand correction committed first (PROJ-118)."""
        sid = src["id"]
        if src["repo_error"]:
            raise Locked(f"Quell-Markdown gesperrt: {src['repo_error']}")
        await self._flush_containing(sid, keep_stage=stage if batch else None)

        cur = None
        fresh = False  # markdown had to be created anew (no state left in git)
        if src["blob"]:
            cur = await self._io(self.repo.read, src["path"])
            if cur is None:
                cur = await self._io(self.repo.cat_blob, src["blob"])
                if md.is_deleted_path(src["path"]):
                    # removed by hand below deleted/ (allowed, PROJ-116 AK-15): continue from git history
                    if cur is None:
                        fresh = True
                        await self._event(con, sid, "warning", "markdown_recreated",
                                          f"Quell-Markdown {src['path']} war nicht mehr in Git vorhanden und "
                                          "wurde neu angelegt; die Stufen laufen neu")
                    else:
                        await self._event(con, sid, "info", "markdown_restored",
                                          f"Quell-Markdown {src['path']} aus der Git-Historie zurückgeholt")
                else:  # deleted by hand (EC-5): continue from the last pipeline state
                    await self._event(con, sid, "error", "file_deleted",
                                      f"Quell-Markdown {src['path']} fehlte und wurde aus Git wiederhergestellt")
            elif await self._io(self.repo.hash_text, cur) != src["blob"]:
                # uncommitted hand edit: commit it first, then write on top (AK-27)
                src = await self._accept_hand_edit(con, src)
                if src["repo_error"]:
                    raise Locked(f"Quell-Markdown gesperrt: {src['repo_error']}")
                if token and not await self._claim_valid(con, src, stage, token):
                    return _discarded(src)
                cur = await self._io(self.repo.read, src["path"])

        old_fm, old_content = md.parse(cur) if cur else ({}, "")
        manual = [m for m in (old_fm.get("manual") or []) if isinstance(m, str)]
        new_fm = dict(old_fm)
        for key, value in (await self._register_fields(con, src)).items():
            if key in md.ALWAYS_REGISTER or key not in manual or key not in new_fm:
                new_fm[key] = value
        if not src["deleted"]:
            new_fm.pop("deleted", None)
        if fresh:
            fields = {"title": src["title"], "language": None, "type": None, **(fields or {})}
            if content is None:
                content = md.original_links(new_fm["locations"])
        for key, value in (fields or {}).items():
            if key not in manual or key not in new_fm:
                new_fm[key] = md.keep_manual_parts(key, value, new_fm.get(key), manual)
        for key in md.BASE_FIELDS:
            new_fm.setdefault(key, None)
        new_fm["manual"] = manual
        if not isinstance(new_fm.get("title"), str) or not new_fm["title"].strip():
            new_fm["title"] = src["title"]
        new_content = content if content is not None and md.CONTENT not in manual else old_content
        new_fm = md.order(new_fm)

        title = new_fm["title"]
        base = md.regular_path(src["path"])
        if src["blob"]:
            base = md.sibling_path(base, sid, title)
        # deleted sources live below deleted/ (git rename keeps the history, PROJ-116 AK-11/13)
        new_path = md.deleted_path(base) if src["deleted"] else base
        text = md.render(new_fm, new_content)
        on_disk = cur is not None and await self._io(self.repo.exists, src["path"])
        if text == cur and new_path == src["path"] and on_disk:
            return {"id": sid, "path": src["path"], "changed": False, "commit": None, "reset": []}

        changed: set[str] = set()
        meta: set[str] = set()
        if src["blob"] and not fresh:
            changed = {k for k in set(old_fm) | set(new_fm)
                       if k not in (*md.META_FIELDS, "manual") and old_fm.get(k) != new_fm.get(k)}
            meta = {k for k in md.META_FIELDS if old_fm.get(k) != new_fm.get(k)}
            if md.normalize_content(old_content) != md.normalize_content(new_content):
                changed.add(md.CONTENT)

        try:
            await self._io(self.repo.write, new_path, text)
            if new_path != src["path"]:
                await self._io(self.repo.remove, src["path"])
            blob = await self._io(self.repo.hash_text, text, True)
            commit = None
            if not batch:
                commit = await self._io(self.repo.commit, {src["path"], new_path}, f"{label}: {sid} {title}", PIPELINE)
        except Exception:
            await self._revert(src["path"], new_path, cur)
            raise
        await con.execute("UPDATE alice.sources SET path = $2, title = $3, blob = $4 WHERE id = $1",
                          sid, new_path, title, blob)
        if batch:
            if self._add_to_batch(stage or label, sid, {src["path"], new_path}) >= self.s.batch_max_files:
                await self._flush_stage(stage or label)
        reset = await self._reset_dependents(con, sid, stage, changed, meta, keep_stages)
        if fresh:
            reset = await self._reset_after(con, sid, "detect")
        src.update(path=new_path, title=title, blob=blob)
        return {"id": sid, "path": new_path, "changed": True, "commit": commit, "reset": reset}

    async def _revert(self, old_path: str, new_path: str, old_text: str | None) -> None:
        """Best effort: undo a file write whose commit failed, so it is not taken for a hand edit."""
        try:
            if new_path != old_path or old_text is None:
                await asyncio.to_thread(self.repo.remove, new_path)
            if old_text is not None:
                await asyncio.to_thread(self.repo.write, old_path, old_text)
        except Exception as exc:
            logger.warning("Could not revert %s after a failed write: %s", new_path, exc)

    # ================================================================ hand corrections
    async def _accept_hand_edit(self, con, src: dict, found_at: str | None = None) -> dict:
        """Take over a foreign change of a source markdown (AK-23/24/28/29, EC-3/4)."""
        sid, path = src["id"], src["path"]
        actual = found_at or path
        text = await self._io(self.repo.read, actual)
        try:
            if text is None:
                raise md.InvalidDocument("Datei ist nicht lesbar (keine UTF-8-Textdatei)")
            fm, content = md.parse(text)
            md.validate(fm, source_id=sid, kind=src["kind"])
        except md.InvalidDocument as exc:
            reason = f"{actual}: {exc}"
            if src["repo_error"] != reason:
                await con.execute("UPDATE alice.sources SET repo_error = $2, repo_error_at = NOW() WHERE id = $1",
                                  sid, reason)
                await self._event(con, sid, "error", "invalid_frontmatter",
                                  f"Hand-Änderung nicht übernommen, Datei gesperrt bis zur Reparatur: {reason}")
                logger.warning("Invalid hand edit of %s, source %s locked: %s", actual, sid, exc)
            src.update(repo_error=reason)
            return src

        base_text = await self._io(self.repo.cat_blob, src["blob"]) if src["blob"] else None
        try:
            base_fm, base_content = md.parse(base_text) if base_text else ({}, "")
        except md.InvalidDocument:
            base_fm, base_content = {}, ""
        top = sorted(k for k in set(base_fm) | set(fm)
                     if k not in ("manual", "id", "kind", "schema", "deleted") and base_fm.get(k) != fm.get(k))
        # fields inside a block (e.g. `fields.amount_gross`) are protected one by one (PROJ-118)
        changed = [p for k in top for p in md.changed_parts(k, base_fm.get(k), fm.get(k))]
        content_changed = md.normalize_content(base_content) != md.normalize_content(content)
        manual = list(fm["manual"])
        for key in changed + ([md.CONTENT] if content_changed else []):
            if key not in manual:
                manual.append(key)
        fm["manual"] = manual
        edited = bool(changed or content_changed or manual != (base_fm.get("manual") or []))

        title = fm["title"]
        new_path = md.sibling_path(path, sid, title)
        out = md.render(fm, content)
        if out != text or actual != new_path:
            await self._io(self.repo.write, new_path, out)
        for p in {actual, path} - {new_path}:
            await self._io(self.repo.remove, p)
        blob = await self._io(self.repo.hash_text, out, True)
        for b in self.batches.values():  # the file is committed now
            b["ids"].pop(sid, None)
        if edited:
            message, author = f"manual: {sid} {title}", HAND
        else:
            message, author = f"restore: {sid} {title}", PIPELINE
        await self._io(self.repo.commit, {path, actual, new_path}, message, author)

        await con.execute("UPDATE alice.sources SET path = $2, title = $3, blob = $4, repo_error = NULL, "
                          "repo_error_at = NULL WHERE id = $1", sid, new_path, title, blob)
        if src["repo_error"]:
            await self._event(con, sid, "info", "unlocked", "Frontmatter repariert, Sperre aufgehoben")
        if changed or content_changed:
            await self._reset_dependents(con, sid, None, set(top) | ({md.CONTENT} if content_changed else set()))
        if edited:
            parts = changed + ([md.CONTENT] if content_changed else [])
            await self._event(con, sid, "info", "hand_correction",
                              "Hand-Korrektur übernommen" + (f": {', '.join(parts)}" if parts else " (manual)"))
            logger.info("Hand correction of %s accepted (%s)", sid, ", ".join(parts) or "manual")
        elif actual != path or new_path != path:
            await self._event(con, sid, "warning", "file_moved",
                              f"Quell-Markdown lag unter {actual} und wurde nach {new_path} zurückgelegt")
        src.update(path=new_path, title=title, blob=blob, repo_error=None)
        return src

    async def scan(self) -> dict:
        """Detect hand corrections: uncommitted changes and commits since the last scan."""
        self.require_available()
        async with self.lock:
            result = await self._scan_locked()
        self.last_scan = time.monotonic()
        return result

    async def _scan_locked(self) -> dict:
        head = await self._io(self.repo.head)
        scanned = await self._io(self.repo.get_ref)
        status = set(await self._io(self.repo.status_paths))
        candidates = set(status)
        if not scanned and head:
            # no scan mark yet (first scan or lost ref): compare every tracked file once
            candidates |= set(await self._io(self.repo.tracked_paths))
        elif scanned and head and scanned != head:
            try:
                candidates |= set(await self._io(self.repo.changed_since, scanned))
            except GitError as exc:
                logger.warning("Cannot diff against last scan (%s); checking uncommitted changes only", exc)
        batch_paths = self._batch_paths()
        batch_ids = self._batch_ids()
        candidates = {p for p in candidates if p.endswith(".md") and p not in batch_paths}
        accepted = locked = restored = removed = 0
        recover: set[str] = set()

        async with self.pool.acquire() as con:
            for r in await con.fetch("SELECT path FROM alice.sources WHERE repo_error IS NOT NULL"):
                candidates.add(r["path"])
            rows = await con.fetch(f"SELECT {SOURCE_COLS} FROM alice.sources WHERE path = ANY($1::text[])",
                                   sorted(candidates))
            targets = {r["id"]: dict(r) for r in rows}
            known_paths = {r["path"] for r in rows}
            found: dict[str, str] = {}
            for p in sorted(candidates - known_paths):
                text = await self._io(self.repo.read, p)
                if text is None:
                    if p in status:  # old name of a renamed pipeline file, or a deleted stray file
                        recover.add(p)
                    continue
                fid = md.frontmatter_id(text)
                row = await con.fetchrow(f"SELECT {SOURCE_COLS} FROM alice.sources WHERE id = $1", fid) if fid else None
                if row and not await self._io(self.repo.exists, row["path"]) and fid not in found:
                    found[fid] = p
                    targets.setdefault(fid, dict(row))
                elif p not in self.warned:
                    self.warned.add(p)
                    logger.warning("Markdown %s does not belong to a known source; left untouched (EC-6)", p)

            for sid in sorted(targets):
                if sid in batch_ids:
                    continue
                async with con.transaction():
                    src = await self._source(con, sid, lock=True)
                    path = src["path"]
                    found_at = None if await self._io(self.repo.exists, path) else found.get(sid)
                    text = await self._io(self.repo.read, found_at or path)
                    if text is None:
                        if src["deleted"] and md.is_deleted_path(path):
                            # removing a markdown below deleted/ is allowed (PROJ-116 AK-14)
                            if await self._io(self.repo.commit, {path}, f"manual: remove {sid} {src['title']}", HAND):
                                await self._event(con, sid, "info", "markdown_removed",
                                                  f"Quell-Markdown {path} unter deleted/ von Hand gelöscht")
                                logger.info("Markdown %s of deleted source %s removed by hand", path, sid)
                                removed += 1
                            continue
                        if src["blob"] and await self._restore(con, src):
                            restored += 1
                        continue
                    if found_at is None and await self._io(self.repo.hash_text, text) == src["blob"]:
                        if src["repo_error"]:  # reverted to the last valid state
                            await con.execute("UPDATE alice.sources SET repo_error = NULL, repo_error_at = NULL "
                                              "WHERE id = $1", sid)
                            await self._event(con, sid, "info", "unlocked", "Frontmatter repariert, Sperre aufgehoben")
                        if path in status:  # pipeline file not committed before a restart (EC-7)
                            recover.add(path)
                        continue
                    src = await self._accept_hand_edit(con, src, found_at)
                    if src["repo_error"]:
                        locked += 1
                    else:
                        accepted += 1

        recover_list = sorted(recover)
        for i in range(0, len(recover_list), self.s.batch_max_files):
            chunk = recover_list[i:i + self.s.batch_max_files]
            await self._io(self.repo.commit, chunk, f"rebuild: recover {len(chunk)} sources", PIPELINE)
        moved = await self._move_deleted()
        head = await self._io(self.repo.head) if moved else head
        if head:
            await self._io(self.repo.set_ref, head)
        return {"accepted": accepted, "moved": moved, "locked": locked, "restored": restored, "removed": removed,
                "recovered": len(recover_list)}

    async def _move_deleted(self, limit: int = 200) -> int:
        """Deleted sources whose markdown is still outside deleted/ (deleted before PROJ-116) → move it."""
        moved = 0
        async with self.pool.acquire() as con:
            ids = [r["id"] for r in await con.fetch(
                "SELECT id FROM alice.sources WHERE deleted AND repo_error IS NULL AND path NOT LIKE $1 "
                "ORDER BY id LIMIT $2", md.DELETED_DIR + "/%", limit)]
            for sid in ids:
                if sid in self._batch_ids():
                    continue
                async with con.transaction():
                    src = await self._source(con, sid, lock=True)
                    if (await self._write_source(con, src, label="locations"))["changed"]:
                        moved += 1
        return moved

    async def _restore(self, con, src: dict) -> bool:
        text = await self._io(self.repo.cat_blob, src["blob"])
        if text is None:
            return False
        await self._io(self.repo.write, src["path"], text)
        await self._io(self.repo.commit, {src["path"]}, f"restore: {src['id']} {src['title']}", PIPELINE)
        await self._event(con, src["id"], "error", "file_deleted",
                          f"Quell-Markdown {src['path']} wurde gelöscht und aus Git wiederhergestellt")
        logger.warning("Source markdown %s was deleted; restored from git", src["path"])
        return True

    # ================================================================ register API
    async def _new_id(self, con) -> str:
        while True:
            sid = "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
            if not await con.fetchval("SELECT 1 FROM alice.sources WHERE id = $1", sid):
                return sid

    async def _reactivate(self, con, src: dict) -> None:
        """The original is back: same id, finished stages stay finished (PROJ-116 AK-13)."""
        await con.execute("UPDATE alice.sources SET deleted = FALSE, deleted_at = NULL WHERE id = $1", src["id"])
        await self._event(con, src["id"], "info", "reactivated", "Original wieder vorhanden: Quelle wieder aktiv")
        src.update(deleted=False, deleted_at=None)

    async def _upsert_location(self, con, source_id: str, loc: dict) -> bool:
        """True if the location is new or came back."""
        row = await con.fetchrow(
            """
            INSERT INTO alice.source_locations (source_id, path, mailbox, folder, uid, message_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (source_id, COALESCE(path, ''), COALESCE(mailbox, ''), COALESCE(folder, ''),
                         COALESCE(message_id, ''))
            DO UPDATE SET last_seen = NOW(), present = TRUE, gone_at = NULL,
                          uid = COALESCE(EXCLUDED.uid, alice.source_locations.uid)
            RETURNING (xmax = 0) AS inserted
            """, source_id, loc.get("path"), loc.get("mailbox"), loc.get("folder"), loc.get("uid"),
            loc.get("message_id"))
        return bool(row["inserted"])

    async def _check_parents(self, con, parents: list[str], self_id: str | None = None) -> None:
        if not parents:
            return
        rows = await con.fetch("SELECT id, kind FROM alice.sources WHERE id = ANY($1::text[])", parents)
        kinds = {r["id"]: r["kind"] for r in rows}
        missing = [p for p in parents if p not in kinds]
        if missing:
            raise Invalid(f"Unbekannte Eltern-Quelle(n): {', '.join(missing)}")
        if any(kinds[p] != "email" for p in parents):
            raise Invalid("Eltern einer Quelle müssen Mails sein (kind = email)")
        if self_id and self_id in parents:
            raise Invalid("Eine Quelle kann nicht ihr eigener Elternteil sein")

    async def register(self, *, kind: str, hash: str, title: str, location: dict, size: int | None = None,
                       modified: datetime | None = None, captured: datetime | None = None,
                       parents: list[str] | None = None, stage: str = "detect", batch: bool = False,
                       complete: bool = False) -> dict:
        """Register a source (AK-11–13). A known hash adds the location/parents to the existing source
        (and reactivates it if it was deleted). `complete` marks `stage` done for a new source (PROJ-116)."""
        self.require_available()
        parents = list(dict.fromkeys(parents or []))
        async with self.lock:
            async with self.pool.acquire() as con, con.transaction():
                await self._require_stage(con, stage)
                row = await con.fetchrow(f"SELECT {SOURCE_COLS} FROM alice.sources WHERE hash = $1 FOR UPDATE", hash)
                if row:
                    src = dict(row)
                    await self._check_parents(con, parents, src["id"])
                    await self._upsert_location(con, src["id"], location)
                    for p in parents:
                        await con.execute("INSERT INTO alice.source_parents (source_id, parent_id) VALUES ($1, $2) "
                                          "ON CONFLICT DO NOTHING", src["id"], p)
                    reactivated = src["deleted"]
                    if reactivated:
                        await self._reactivate(con, src)
                    written = None
                    if not src["repo_error"]:
                        written = await self._write_source(con, src, label="locations", batch=batch, stage=stage)
                    elif reactivated:  # locked markdown is not rewritten (PROJ-119)
                        await self._reset_dependents(con, src["id"], None, (), ("deleted",))
                    return {"id": src["id"], "created": False, "path": src["path"], "reactivated": reactivated,
                            "locked": bool(src["repo_error"]), "changed": bool(written and written["changed"])}

                await self._check_parents(con, parents)
                sid = await self._new_id(con)
                captured = captured or datetime.now(timezone.utc)
                if captured.tzinfo is None:
                    captured = captured.replace(tzinfo=self.s.tz)
                path = md.rel_path(kind, captured.astimezone(self.s.tz), sid, title)
                await con.execute(
                    "INSERT INTO alice.sources (id, kind, hash, size, modified, captured, title, path) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)", sid, kind, hash, size, modified, captured, title, path)
                await con.execute(
                    "INSERT INTO alice.source_stages (source_id, stage, state) "
                    "SELECT $1, name, CASE WHEN $2 = ANY(skip_kinds) THEN 'skipped' "
                    "WHEN $3 AND name = $4 THEN 'done' ELSE 'pending' END "
                    "FROM alice.pipeline_stages", sid, kind, complete, stage)
                await self._upsert_location(con, sid, location)
                for p in parents:
                    await con.execute("INSERT INTO alice.source_parents (source_id, parent_id) VALUES ($1, $2)", sid, p)
                if complete:
                    await self._mark_served(con, stage, {kind})
                src = await self._source(con, sid)
                written = await self._write_source(
                    con, src, label=stage, stage=stage, batch=batch,
                    fields={"title": title, "language": None, "type": None},
                    content=md.original_links([location]))
                pending = await con.fetch("SELECT stage FROM alice.source_stages WHERE source_id = $1 "
                                          "AND state = 'pending'", sid)
        now = time.time()
        for r in pending:
            await self.queue.push(r["stage"], {sid: now})
        return {"id": sid, "created": True, "path": written["path"], "reactivated": False, "locked": False,
                "changed": True}

    async def write_document(self, source_id: str, *, stage: str, fields: dict | None = None,
                             content: str | None = None, batch: bool = False, token: str | None = None,
                             label: str | None = None, keep_stages: list[str] | None = None) -> dict:
        """A stage writes fields and/or the content part (AK-5, AK-7, AK-25–27).
        `label` (PROJ-124): commit text instead of the stage name; `keep_stages`: stages this write does
        not reset.
        With `token` (PROJ-118) the write only happens while `stage` is still running under this claim
        and the source is not deleted; otherwise the result is discarded (`discarded: true`)."""
        fields = fields or {}
        bad = [k for k in fields if not isinstance(k, str) or not FIELD_NAME.match(k)]
        if bad:
            raise Invalid(f"Ungültige Feldnamen: {', '.join(map(str, bad))}")
        protected = sorted(PROTECTED_FIELDS & set(fields))
        if protected:
            raise Invalid(f"Felder werden vom Register gepflegt und können nicht geschrieben werden: {', '.join(protected)}")
        if "title" in fields and (not isinstance(fields["title"], str) or not fields["title"].strip()):
            raise Invalid("title muss ein nicht leerer Text sein")
        self.require_available()
        async with self.lock:
            async with self.pool.acquire() as con, con.transaction():
                await self._require_stage(con, stage)
                src = await self._source(con, source_id, lock=True)
                if token and not await self._claim_valid(con, src, stage, token):
                    return _discarded(src)
                if not batch:  # work of a rebuild run is committed in batch commits (PROJ-120, AK-9)
                    batch = bool(await con.fetchval(
                        "SELECT rebuild_run IS NOT NULL FROM alice.source_stages WHERE source_id = $1 AND stage = $2",
                        source_id, stage))
                return await self._write_source(con, src, label=label or stage, stage=stage, fields=fields,
                                                content=content, batch=batch, token=token,
                                                keep_stages=tuple(keep_stages or ()))

    async def read_document(self, source_id: str) -> dict:
        self.require_available()
        async with self.pool.acquire() as con:
            src = await self._source(con, source_id)
        text = await self._io(self.repo.read, src["path"])
        if text is None:
            raise Conflict(f"Quell-Markdown {src['path']} fehlt (wird beim nächsten Prüflauf wiederhergestellt)")
        try:
            fm, content = md.parse(text)
        except md.InvalidDocument as exc:
            raise Locked(f"Quell-Markdown ungültig: {exc}") from None
        return {"id": source_id, "path": src["path"], "frontmatter": fm, "content": content,
                "locked": src["repo_error"]}

    async def add_location(self, source_id: str, location: dict) -> dict:
        """New or changed location of the original (AK-6): only `locations` changes."""
        self.require_available()
        async with self.lock:
            async with self.pool.acquire() as con, con.transaction():
                src = await self._source(con, source_id, lock=True)
                await self._upsert_location(con, source_id, location)
                reactivated = src["deleted"]
                if reactivated:
                    await self._reactivate(con, src)
                if src["repo_error"]:
                    if reactivated:  # locked markdown is not rewritten (PROJ-119)
                        await self._reset_dependents(con, source_id, None, (), ("deleted",))
                    return {"id": source_id, "deleted": False, "locked": True, "changed": False}
                written = await self._write_source(con, src, label="locations")
                return {"id": source_id, "deleted": False, "locked": False, "changed": written["changed"]}

    async def remove_location(self, source_id: str, location: dict) -> dict:
        """A location disappeared; without any present location the source is deleted (AK-14)."""
        self.require_available()
        async with self.lock:
            async with self.pool.acquire() as con, con.transaction():
                src = await self._source(con, source_id, lock=True)
                hit = await con.fetchval(
                    "UPDATE alice.source_locations SET present = FALSE, gone_at = NOW() "
                    "WHERE source_id = $1 AND path IS NOT DISTINCT FROM $2 AND mailbox IS NOT DISTINCT FROM $3 "
                    "AND message_id IS NOT DISTINCT FROM $4 AND folder IS NOT DISTINCT FROM $5 AND present RETURNING id",
                    source_id, location.get("path"), location.get("mailbox"), location.get("message_id"),
                    location.get("folder"))
                if hit is None:
                    raise NotFound("Fundort an dieser Quelle nicht (mehr) vorhanden")
                remaining = await con.fetchval("SELECT count(*) FROM alice.source_locations "
                                               "WHERE source_id = $1 AND present", source_id)
                if remaining == 0 and not src["deleted"]:
                    src["deleted_at"] = await con.fetchval(
                        "UPDATE alice.sources SET deleted = TRUE, deleted_at = NOW() WHERE id = $1 RETURNING deleted_at",
                        source_id)
                    src["deleted"] = True
                    await self._event(con, source_id, "info", "deleted", "Kein Fundort mehr vorhanden: Quelle gelöscht")
                changed = False
                if not src["repo_error"]:
                    changed = (await self._write_source(con, src, label="locations"))["changed"]
                elif remaining == 0:  # locked markdown is not rewritten: reset the deletion stages here
                    await self._reset_dependents(con, source_id, None, (), ("deleted",))
                return {"id": source_id, "deleted": remaining == 0, "locked": bool(src["repo_error"]),
                        "changed": changed}

    async def update_original(self, source_id: str, *, hash: str, size: int | None, modified: datetime | None,
                              stage: str = "detect") -> dict:
        """Original changed in place (EC-8): update hash/size/modified."""
        self.require_available()
        async with self.lock:
            async with self.pool.acquire() as con, con.transaction():
                await self._require_stage(con, stage)
                src = await self._source(con, source_id, lock=True)
                other = await con.fetchval("SELECT id FROM alice.sources WHERE hash = $1 AND id <> $2", hash, source_id)
                if other:
                    raise Conflict(f"Hash gehört bereits zur Quelle {other}")
                await con.execute("UPDATE alice.sources SET hash = $2, size = $3, modified = $4 WHERE id = $1",
                                  source_id, hash, size, modified)
                src.update(hash=hash, size=size, modified=modified)
                # new content: every stage after the reporting one has to run again (PROJ-116 AK-16)
                reset = await self._reset_after(con, source_id, stage)
                if src["repo_error"]:
                    return {"id": source_id, "locked": True, "changed": False, "reset": reset}
                written = await self._write_source(con, src, label=stage, stage=stage)
                return {"id": source_id, "locked": False, "changed": written["changed"],
                        "reset": sorted(set(reset) | set(written["reset"]))}

    async def get_source(self, source_id: str) -> dict:
        async with self.pool.acquire() as con:
            src = await self._source(con, source_id)
            locs = await con.fetch("SELECT path, mailbox, folder, uid, message_id, present, first_seen, last_seen, gone_at "
                                   "FROM alice.source_locations WHERE source_id = $1 ORDER BY first_seen, id",
                                   source_id)
            parents = await self._parents(con, source_id)
            children = [r["source_id"] for r in await con.fetch(
                "SELECT source_id FROM alice.source_parents WHERE parent_id = $1 ORDER BY created_at, source_id "
                "LIMIT 1000", source_id)]
            stages = await con.fetch(
                "SELECT ss.stage, ss.state, ss.attempts, ss.last_error, ss.last_attempt_at, ss.next_retry_at, "
                "ss.started_at FROM alice.source_stages ss JOIN alice.pipeline_stages ps ON ps.name = ss.stage "
                "WHERE ss.source_id = $1 ORDER BY ps.position, ps.name", source_id)
            events = await con.fetch("SELECT level, event, message, created_at FROM alice.source_events "
                                     "WHERE source_id = $1 ORDER BY created_at DESC, id DESC LIMIT 20", source_id)
        src.pop("blob", None)
        return {**src, "locations": [dict(r) for r in locs], "parents": parents, "children": children,
                "stages": {r["stage"]: dict(r) for r in stages}, "events": [dict(r) for r in events]}

    async def find_by_hash(self, hash: str) -> dict:
        async with self.pool.acquire() as con:
            sid = await con.fetchval("SELECT id FROM alice.sources WHERE hash = $1", hash)
        if not sid:
            raise NotFound("Keine Quelle mit diesem Hash")
        return await self.get_source(sid)

    # ================================================================ stages
    async def list_stages(self) -> list[dict]:
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT name, position, skip_kinds, resets_on_content_change, resets_on_fields "
                                   "FROM alice.pipeline_stages ORDER BY position, name")
        return [dict(r) for r in rows]

    async def add_stage(self, *, name: str, position: int, skip_kinds: list[str],
                        resets_on_content_change: bool, resets_on_fields: list[str] | None = None) -> dict:
        """New stage from a follow-up feature (AK-21): existing sources get a state, no migration."""
        async with self.pool.acquire() as con, con.transaction():
            created = await con.fetchval(
                "INSERT INTO alice.pipeline_stages (name, position, skip_kinds, resets_on_content_change, "
                "resets_on_fields) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (name) DO NOTHING RETURNING name",
                name, position, skip_kinds, resets_on_content_change, resets_on_fields or [])
            if not created:
                raise Conflict(f"Stufe {name} existiert bereits")
            n = await con.execute(
                "INSERT INTO alice.source_stages (source_id, stage, state) "
                "SELECT id, $1, CASE WHEN kind = ANY($2::text[]) THEN 'skipped' ELSE 'pending' END "
                "FROM alice.sources ON CONFLICT DO NOTHING", name, skip_kinds)
        await self.resync_queue()
        return {"name": name, "sources": int(n.split()[-1])}

    _CLAIM_SET = ("state = 'running', claim_token = gen_random_uuid(), started_at = NOW(), "
                  "last_attempt_at = NOW()")
    # a pending stage with next_retry_at in the future was released with a delay (PROJ-117)
    _CLAIMABLE = ("s.repo_error IS NULL AND NOT s.deleted AND ((ss.state = 'pending' "
                  "AND (ss.next_retry_at IS NULL OR ss.next_retry_at <= NOW())) "
                  "OR (ss.state = 'failed' AND ss.next_retry_at <= NOW()))")
    # PROJ-119: a stage that removes derived data also gets deleted sources (even locked ones, it does
    # not read their markdown), regardless of `requires`
    _CLAIMABLE_DELETED = ("(s.deleted OR s.repo_error IS NULL) AND ((ss.state = 'pending' "
                          "AND (ss.next_retry_at IS NULL OR ss.next_retry_at <= NOW())) "
                          "OR (ss.state = 'failed' AND ss.next_retry_at <= NOW()))")
    _CLAIM_RETURN = ("ss.source_id, ss.stage, ss.claim_token::text AS token, ss.attempts, "
                     "s.kind, s.path, s.title, s.hash, s.deleted, ss.rebuild_run IS NOT NULL AS rebuild")

    async def claim(self, stage: str, limit: int = 1, kinds: list[str] | None = None,
                    requires: list[str] | None = None, include_deleted: bool = False) -> dict:
        """Take over due work exclusively (AK-15). Paused while the repo is unavailable (AK-30).
        `kinds` restricts the work to these source kinds (PROJ-117); such claims are served from the
        register, so the Redis queue is never drained of sources of other kinds.
        `requires` (PROJ-118): only sources whose listed stages are done (or skipped), e.g. classify
        after extract; such claims are served from the register as well.
        `include_deleted` (PROJ-119): deleted sources are handed out as well (`deleted: true`), without
        the `requires` check, so a stage can remove what it derived from them."""
        async with self.pool.acquire() as con:
            await self._require_stage(con, stage)
            if not self.available:
                return {"paused": True, "reason": self.unavailable_reason, "items": []}
            items = []
            for name in requires or []:
                await self._require_stage(con, name)
            plain = not kinds and not requires and not include_deleted
            ids = await self.queue.due(stage, limit * 5) if plain else None
            if ids is not None:
                for sid in ids:
                    row = await con.fetchrow(
                        f"UPDATE alice.source_stages ss SET {self._CLAIM_SET} FROM alice.sources s "
                        f"WHERE ss.source_id = $1 AND ss.stage = $2 AND s.id = ss.source_id AND {self._CLAIMABLE} "
                        f"RETURNING {self._CLAIM_RETURN}", sid, stage)
                    await self.queue.remove(stage, sid)
                    if row:
                        items.append(dict(row))
                        if len(items) >= limit:
                            break
            if ids is None or (len(items) < limit and not await self.queue.due(stage, 1)):
                # register: normal work first, rebuild work (PROJ-120, never in the Redis queue) after it
                claimable = self._CLAIMABLE_DELETED if include_deleted else self._CLAIMABLE
                rows = await con.fetch(
                    f"""
                    WITH picked AS (
                        SELECT ss.source_id FROM alice.source_stages ss JOIN alice.sources s ON s.id = ss.source_id
                         WHERE ss.stage = $1 AND {claimable}
                           AND ($3::text[] IS NULL OR s.kind = ANY($3::text[]))
                           AND ($4::text[] IS NULL OR s.deleted OR NOT EXISTS (
                                SELECT 1 FROM alice.source_stages r WHERE r.source_id = ss.source_id
                                   AND r.stage = ANY($4::text[]) AND r.state NOT IN ('done', 'skipped')))
                           AND ($5::bool OR ss.rebuild_run IS NOT NULL)
                         ORDER BY ss.rebuild_run IS NOT NULL, COALESCE(ss.next_retry_at, ss.updated_at)
                         LIMIT $2 FOR UPDATE OF ss SKIP LOCKED)
                    UPDATE alice.source_stages ss SET {self._CLAIM_SET}
                      FROM picked, alice.sources s
                     WHERE ss.stage = $1 AND ss.source_id = picked.source_id AND s.id = ss.source_id
                       AND {claimable}
                    RETURNING {self._CLAIM_RETURN}
                    """, stage, limit - len(items), kinds or None, requires or None, ids is None)
                items.extend(sorted((dict(r) for r in rows), key=lambda r: r["rebuild"]))
            await self._mark_served(con, stage, {it["kind"] for it in items})
        return {"paused": False, "reason": None, "items": items}

    async def _mark_served(self, con, stage: str, kinds) -> None:
        """PROJ-120: remember that a stage service serves `stage` for these kinds (option A of #12)."""
        for kind in sorted(set(kinds) - {k for st, k in self.served if st == stage}):
            await con.execute("INSERT INTO alice.pipeline_stage_served (stage, kind) VALUES ($1, $2) "
                              "ON CONFLICT DO NOTHING", stage, kind)
            self.served.add((stage, kind))

    async def _finish(self, sql: str, source_id: str, stage: str, *args):
        async with self.pool.acquire() as con:
            row = await con.fetchrow(sql, source_id, stage, *args)
            if row:
                return dict(row)
            exists = await con.fetchval("SELECT state FROM alice.source_stages WHERE source_id = $1 AND stage = $2",
                                        source_id, stage)
        if exists is None:
            raise NotFound(f"Stufe {stage} der Quelle {source_id} nicht gefunden")
        raise Conflict(f"Stufe ist nicht (mehr) von diesem Worker übernommen (Zustand: {exists})")

    async def complete(self, source_id: str, stage: str, token: str) -> dict:
        return await self._finish(
            "UPDATE alice.source_stages SET state = 'done', last_error = NULL, next_retry_at = NULL, "
            "claim_token = NULL, started_at = NULL WHERE source_id = $1 AND stage = $2 AND state = 'running' "
            "AND claim_token = $3::uuid RETURNING state, attempts", source_id, stage, token)

    async def fail(self, source_id: str, stage: str, token: str, error: str, permanent: bool = False) -> dict:
        """Failure → attempts +1 and next retry by backoff; the 5th failure is permanent (AK-16/17).
        `permanent` (PROJ-117): the error cannot go away by retrying (password, broken file) →
        failed_permanent at once, without waiting for the remaining attempts."""
        row = await self._finish(
            f"""
            UPDATE alice.source_stages
               SET attempts = attempts + 1, last_error = $4, last_attempt_at = NOW(),
                   claim_token = NULL, started_at = NULL,
                   state = CASE WHEN $6 OR attempts + 1 >= {MAX_ATTEMPTS} THEN 'failed_permanent' ELSE 'failed' END,
                   next_retry_at = CASE WHEN $6 OR attempts + 1 >= {MAX_ATTEMPTS} THEN NULL
                                   ELSE NOW() + make_interval(secs => ($5::int[])[attempts + 1]) END
             WHERE source_id = $1 AND stage = $2 AND state = 'running' AND claim_token = $3::uuid
            RETURNING state, attempts, last_error, last_attempt_at, next_retry_at
            """, source_id, stage, token, error[:4000], BACKOFF_SECONDS, permanent)
        if row["next_retry_at"]:
            await self.queue.push(stage, {source_id: row["next_retry_at"].timestamp()})
        return row

    async def release(self, source_id: str, stage: str, token: str, delay_seconds: int = 0) -> dict:
        """Give work back without counting an attempt (e.g. repo unavailable, AK-30).
        `delay_seconds` (PROJ-117): hand the work out again only after this time (e.g. original missing)."""
        row = await self._finish(
            "UPDATE alice.source_stages SET state = 'pending', claim_token = NULL, started_at = NULL, "
            "next_retry_at = CASE WHEN $4 > 0 THEN NOW() + make_interval(secs => $4::int) ELSE NULL END "
            "WHERE source_id = $1 AND stage = $2 AND state = 'running' AND claim_token = $3::uuid "
            "RETURNING state, attempts, next_retry_at", source_id, stage, token, delay_seconds)
        due = row["next_retry_at"].timestamp() if row["next_retry_at"] else time.time()
        await self.queue.push(stage, {source_id: due})
        return row

    async def heartbeat(self, source_id: str, stage: str, token: str) -> dict:
        """Sign of life of the worker (PROJ-117, AK-33): the stage counts as running from now on,
        so a long extraction is not taken for a hanging one (reset_stale)."""
        return await self._finish(
            "UPDATE alice.source_stages SET started_at = NOW() "
            "WHERE source_id = $1 AND stage = $2 AND state = 'running' AND claim_token = $3::uuid "
            "RETURNING state, attempts, started_at", source_id, stage, token)

    async def retry(self, source_id: str, stage: str) -> dict:
        """Manual retry (AK-18): pending with attempt counter 0."""
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "UPDATE alice.source_stages SET state = 'pending', attempts = 0, last_error = NULL, "
                "next_retry_at = NULL, rebuild_run = NULL WHERE source_id = $1 AND stage = $2 "
                "AND state IN ('pending', 'failed', 'failed_permanent', 'done') RETURNING state, attempts",
                source_id, stage)
            if not row:
                state = await con.fetchval("SELECT state FROM alice.source_stages WHERE source_id = $1 AND stage = $2",
                                           source_id, stage)
                if state is None:
                    raise NotFound(f"Stufe {stage} der Quelle {source_id} nicht gefunden")
                raise Conflict(f"Stufe im Zustand {state} kann nicht wiederholt werden")
        await self.queue.push(stage, {source_id: time.time()})
        return dict(row)

    async def reset_stale(self) -> int:
        """`running` longer than the timeout (worker crashed) → pending, not a failed attempt (AK-19)."""
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "UPDATE alice.source_stages SET state = 'pending', claim_token = NULL, started_at = NULL "
                "WHERE state = 'running' AND started_at < NOW() - make_interval(secs => $1::int) "
                "RETURNING source_id, stage", self.s.stale_running_seconds)
        now = time.time()
        for r in rows:
            logger.warning("Stage %s of %s was running too long; back to pending", r["stage"], r["source_id"])
            await self.queue.push(r["stage"], {r["source_id"]: now})
        return len(rows)

    async def resync_queue(self) -> bool:
        """Rebuild the Redis queue from the register (AK-22)."""
        async with self.pool.acquire() as con:
            stages = await self._stage_names(con)
            rows = await con.fetch(
                "SELECT stage, source_id, EXTRACT(EPOCH FROM COALESCE(next_retry_at, updated_at))::float8 AS due "
                "FROM alice.source_stages WHERE state IN ('pending', 'failed') AND rebuild_run IS NULL")
        self.last_resync = time.monotonic()
        return await self.queue.rebuild(stages, [(r["stage"], r["source_id"], r["due"]) for r in rows])

    # ================================================================ rebuild + reconciliation (PROJ-120)
    async def release_rebuild(self, run_id: int, items: list[dict]) -> dict:
        """A rebuild run releases a portion: the listed stages → pending, attempts 0, flagged with the run.
        Running stages stay untouched; a stage already flagged with this run is not reset again (no double
        release after a crash). Deleted and locked sources are not released and reported back."""
        ids = [it["id"] for it in items]
        pairs = [(it["id"], st) for it in items for st in it["stages"]]
        async with self.pool.acquire() as con, con.transaction():
            rows = await con.fetch("SELECT id, deleted, repo_error IS NOT NULL AS locked FROM alice.sources "
                                   "WHERE id = ANY($1::text[])", ids)
            state = {r["id"]: r for r in rows}
            await con.execute(
                """
                UPDATE alice.source_stages ss
                   SET state = 'pending', attempts = 0, last_error = NULL, next_retry_at = NULL,
                       claim_token = NULL, started_at = NULL, rebuild_run = $1
                  FROM alice.sources s, unnest($2::text[], $3::text[]) AS r(source_id, stage)
                 WHERE ss.source_id = r.source_id AND ss.stage = r.stage AND s.id = ss.source_id
                   AND NOT s.deleted AND s.repo_error IS NULL
                   AND ss.state NOT IN ('skipped', 'running') AND ss.rebuild_run IS DISTINCT FROM $1
                """, run_id, [p[0] for p in pairs], [p[1] for p in pairs])
        out = {"released": [], "deleted": [], "locked": [], "unknown": []}
        for sid in ids:
            r = state.get(sid)
            key = "unknown" if r is None else "deleted" if r["deleted"] else "locked" if r["locked"] else "released"
            out[key].append(sid)
        return out

    async def add_event(self, source_id: str, level: str, event: str, message: str) -> dict:
        async with self.pool.acquire() as con:
            await self._source(con, source_id)
            await self._event(con, source_id, level, event, message)
        return {"id": source_id, "event": event}

    async def repo_check(self) -> dict:
        """Level 2 of the reconciliation (register <-> repo), read only: sources without markdown,
        markdowns in the wrong place (deleted <-> deleted/), markdowns without register entry and
        markdowns whose `id`/`kind` do not match the register. Files whose git blob matches the
        blob the pipeline wrote are not read."""
        self.require_available()
        async with self.lock:
            blobs = await self._io(self.repo.index_blobs)
            untracked = set(await self._io(self.repo.untracked_paths))
            gone = set(await self._io(self.repo.deleted_paths))
        present = {p for p in (set(blobs) - gone) | untracked if p.endswith(".md")}
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT id, kind, path, blob, deleted, repo_error, title FROM alice.sources")
        by_id = {r["id"]: r for r in rows}
        paths = {r["path"] for r in rows}
        missing: dict[str, dict] = {}
        findings: list[dict] = []
        for r in rows:
            path = r["path"]
            if path not in present:
                missing[r["id"]] = {"gap": "markdown_missing", "id": r["id"], "path": path, "action": "restore"}
                continue
            if bool(r["deleted"]) != md.is_deleted_path(path):
                findings.append({"gap": "wrong_place", "id": r["id"], "path": path, "action": "move",
                                 "detail": "gelöschte Quelle außerhalb von deleted/" if r["deleted"]
                                 else "aktive Quelle unter deleted/"})
                continue
            if not r["repo_error"] and path not in untracked and blobs.get(path) == r["blob"]:
                continue  # exactly what the pipeline wrote
            # locked sources are read as well: a `kind` changed by hand locks the source at the next
            # scan, the reconciliation still has to report it (AK-27). Unparsable YAML (kind None) of a
            # locked source is its visible lock error, not a mismatch.
            text = await self._io(self.repo.read, path)
            fm_id, fm_kind = self._fm_id_kind(text)
            kind_differs = fm_kind != r["kind"] and (fm_kind is not None or not r["repo_error"])
            if fm_id is not None and (fm_id != r["id"] or kind_differs):
                findings.append({"gap": "frontmatter_mismatch", "id": r["id"], "path": path, "action": None,
                                 "detail": f"Frontmatter id={fm_id} kind={fm_kind}, Register id={r['id']} "
                                           f"kind={r['kind']}"})
        for path in sorted(present - paths):
            text = await self._io(self.repo.read, path)
            fm_id, fm_kind = self._fm_id_kind(text)
            src = by_id.get(fm_id) if fm_id else None
            if src is not None and fm_id in missing and fm_kind == src["kind"] and "found_at" not in missing[fm_id]:
                missing[fm_id]["found_at"] = path  # moved by hand: put it back
                continue
            if src is None:
                detail = "Markdown ohne Registereintrag" + (f" (id {fm_id})" if fm_id else "")
            elif fm_kind != src["kind"]:
                detail = f"kind {fm_kind} passt nicht zum Register ({src['kind']}) der Quelle {fm_id}"
            else:
                detail = f"weitere Markdown zur Quelle {fm_id} (registriert unter {src['path']})"
            findings.append({"gap": "markdown_orphan", "id": None, "path": path, "action": None, "detail": detail})
        for f in missing.values():
            if "found_at" in f:
                f["detail"] = f"Markdown liegt unter {f['found_at']}"
            elif by_id[f["id"]]["blob"] is None:
                f["detail"] = "noch nie geschrieben"
        return {"sources": len(rows), "files": len(present), "findings": list(missing.values()) + findings}

    @staticmethod
    def _fm_id_kind(text: str | None) -> tuple[str | None, str | None]:
        if text is None:
            return None, None
        try:
            fm, _ = md.parse(text)
        except md.InvalidDocument:
            return md.frontmatter_id(text), None
        return (str(fm["id"]) if fm.get("id") is not None else None,
                str(fm["kind"]) if fm.get("kind") is not None else None)

    async def repo_repair(self, items: list[dict]) -> dict:
        """Repairs of level 2: `restore` (moved file back, last state from git, else a new base markdown
        with the stages from extract on pending) and `move` (git rename to the right place).
        Every repair gets an event at the source."""
        self.require_available()
        results = []
        async with self.lock:
            async with self.pool.acquire() as con:
                for it in items:
                    try:
                        async with con.transaction():
                            src = await self._source(con, it["id"], lock=True)
                            done = await (self._repair_restore(con, src, it.get("found_at"))
                                          if it["action"] == "restore" else self._repair_move(con, src))
                        results.append({"id": it["id"], **done})
                    except RepoUnavailable:
                        raise
                    except (NotFound, Conflict, GitError, md.InvalidDocument) as exc:
                        results.append({"id": it["id"], "repaired": False, "detail": str(exc)})
        return {"results": results}

    async def _repair_restore(self, con, src: dict, found_at: str | None) -> dict:
        sid, path = src["id"], src["path"]
        if await self._io(self.repo.exists, path):
            return {"repaired": False, "detail": "Markdown ist wieder vorhanden"}
        if src["repo_error"]:
            raise Locked(f"Quell-Markdown gesperrt: {src['repo_error']}")
        if found_at and await self._io(self.repo.exists, found_at):
            src = await self._accept_hand_edit(con, src, found_at)
            if src["repo_error"]:
                return {"repaired": False, "detail": src["repo_error"]}
            message = f"Abgleich: Quell-Markdown von {found_at} nach {src['path']} zurückgelegt"
            await self._event(con, sid, "info", "reconcile_moved", message)
            return {"repaired": True, "how": "moved_back", "path": src["path"]}
        text = await self._io(self.repo.cat_blob, src["blob"]) if src["blob"] else None
        if text is None:
            text = await self._io(self.repo.last_version, path)
        if text is not None:
            await self._io(self.repo.write, path, text)
            blob = await self._io(self.repo.hash_text, text, True)
            await self._io(self.repo.commit, {path}, f"restore: {sid} {src['title']}", PIPELINE)
            await con.execute("UPDATE alice.sources SET blob = $2 WHERE id = $1", sid, blob)
            await self._event(con, sid, "warning", "reconcile_restored",
                              f"Abgleich: fehlende Quell-Markdown {path} aus der Git-Historie wiederhergestellt")
            return {"repaired": True, "how": "restored", "path": path}
        src["blob"] = None  # nothing left in git: new base markdown, every stage runs again
        written = await self._write_source(
            con, src, label="restore", fields={"title": src["title"], "language": None, "type": None},
            content=md.original_links(await self._present_locations(con, sid)))
        reset = await self._reset_after(con, sid, "detect")
        await self._event(con, sid, "warning", "reconcile_recreated",
                          "Abgleich: Quell-Markdown fehlte auch in der Git-Historie, Basis-Markdown neu angelegt; "
                          "die Stufen laufen neu")
        return {"repaired": True, "how": "recreated", "path": written["path"], "reset": reset}

    async def _repair_move(self, con, src: dict) -> dict:
        if bool(src["deleted"]) == md.is_deleted_path(src["path"]):
            return {"repaired": False, "detail": "Markdown liegt bereits am richtigen Ort"}
        old = src["path"]
        written = await self._write_source(con, src, label="locations")
        await self._event(con, src["id"], "info", "reconcile_moved",
                          f"Abgleich: Quell-Markdown von {old} nach {written['path']} verschoben")
        return {"repaired": True, "how": "moved", "path": written["path"]}

    # ================================================================ background
    async def tick(self) -> None:
        """One round of the background monitor."""
        await self.check_repo()
        try:
            await self.reset_stale()
        except Exception as exc:
            logger.warning("stale stage check failed: %s", exc)
        if self.available:
            try:
                await self.flush_due()
                if self.force_scan or time.monotonic() - self.last_scan >= self.s.scan_interval_seconds:
                    self.force_scan = False
                    await self.scan()
            except RepoBusy as exc:
                logger.info("Repo busy, retrying later: %s", exc)
                self.force_scan = True
            except RepoUnavailable:
                pass  # already logged by _set_available
            except Exception:
                logger.exception("repo maintenance failed")
        try:
            if not await self.queue.is_ready() or time.monotonic() - self.last_resync >= QUEUE_RESYNC_SECONDS:
                await self.resync_queue()
        except Exception as exc:
            logger.warning("queue resync failed: %s", exc)
        self.last_tick = time.monotonic()
