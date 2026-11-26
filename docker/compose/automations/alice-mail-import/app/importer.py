"""IMAP → mail archive → register (stage detect), the nightly reconciliation with the server and the
levels 5/6 of the completeness check (PROJ-120).

Per mailbox at most one connection at a time, also across instances: a PostgreSQL advisory lock
guards every piece of work on a mailbox (AK-9, AK-48). The progress is the set of known locations in
the register, so a restart continues exactly where it stopped (AK-45, EC-12)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import mime
from .archive import Archive, ArchiveUnavailable, month_dir
from .config import Settings
from .crypto import DecryptError, decrypt_password
from .imap import ConnectionLost, ImapError, ImapSession
from .registry import RegistryClient, RegistryConflict, RegistryError, RegistryNotFound, RegistryUnavailable

logger = logging.getLogger("alice-mail-import")

LOCK_NAMESPACE = 1230  # pg advisory lock: (namespace, hashtext(mailbox id))
NIGHTLY_LOCK = 1231
_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
MAILBOX_COLS = ("id, display_name, imap_host, imap_port, imap_username, password_enc, ssl_enabled, sync_interval, "
                "start_date, status, next_sync_at")
FUTURE_TOLERANCE = timedelta(days=1)


def archive_key(display_name: str, mailbox_id) -> str:
    """Stable, file-name safe archive key: slug of the display name at the first import + id prefix."""
    text = "".join(_UMLAUTS.get(c, c) for c in str(display_name or ""))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40].rstrip("-") or "postfach"
    return f"{slug}-{str(mailbox_id).replace('-', '')[:8]}"


class Paused(Exception):
    """Archive or register not available: stop without changes (AK-44)."""


@dataclass
class SyncResult:
    imported: int = 0
    linked: int = 0
    failed: int = 0
    more: bool = False
    folders: list[str] = field(default_factory=list)


class Importer:
    def __init__(self, settings: Settings, pool, registry: RegistryClient, archive: Archive | None = None,
                 session_factory=None):
        self.s = settings
        self.pool = pool
        self.registry = registry
        self.archive = archive or Archive(settings.archive_path)
        self.session_factory = session_factory or (lambda mb, pw: ImapSession(
            mb["imap_host"], mb["imap_port"], mb["ssl_enabled"], mb["imap_username"], pw,
            settings.imap_timeout_seconds))
        self.running: dict[str, asyncio.Task] = {}
        self.paused_reason = ""
        self.last_tick = time.monotonic()
        self.stats = {"imported": 0, "linked": 0, "failed": 0, "removed": 0}
        self.nightly_task: asyncio.Task | None = None
        self.last_nightly_attempt = float("-inf")

    # ================================================================ loop
    async def run(self) -> None:
        try:
            removed = await asyncio.to_thread(self.archive.cleanup_tmp)
            if removed:
                logger.info("Removed %d temporary leftovers in the mail archive", removed)
        except Exception as exc:
            logger.warning("Cleanup of the mail archive failed: %s", exc)
        while True:
            self.last_tick = time.monotonic()
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("import tick failed")
            await asyncio.sleep(self.s.tick_seconds)

    async def stop(self) -> None:
        tasks = list(self.running.values()) + ([self.nightly_task] if self.nightly_task else [])
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def tick(self) -> None:
        for mid in [m for m, t in self.running.items() if t.done()]:
            self.running.pop(mid)
        if self.nightly_task is None or self.nightly_task.done():
            if await self.nightly_due() and time.monotonic() - self.last_nightly_attempt >= 600:
                self.last_nightly_attempt = time.monotonic()
                self.nightly_task = asyncio.create_task(self.nightly())
        if self.nightly_task is not None and not self.nightly_task.done():
            return  # the nightly run works the mailboxes itself
        try:
            await self.check_ready()
        except Paused:
            return
        free = self.s.max_parallel_mailboxes - len(self.running)
        if free <= 0:
            return
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                f"SELECT {MAILBOX_COLS} FROM alice.imap_mailboxes "
                "WHERE next_sync_at IS NULL OR next_sync_at <= NOW() ORDER BY next_sync_at NULLS FIRST LIMIT $1",
                free + len(self.running))
        for mb in rows:
            key = str(mb["id"])
            if key in self.running or len(self.running) >= self.s.max_parallel_mailboxes:
                continue
            self.running[key] = asyncio.create_task(self.sync_mailbox(dict(mb)))

    async def check_ready(self) -> None:
        reason = ""
        try:
            await asyncio.to_thread(self.archive.check)
        except ArchiveUnavailable as exc:
            reason = str(exc)
        if not reason:
            ok, why = await self.registry.available()
            if not ok:
                reason = why
        if reason:
            if reason != self.paused_reason:
                logger.warning("Mail import paused: %s", reason)
            self.paused_reason = reason
            raise Paused(reason)
        if self.paused_reason:
            logger.info("Mail import continues (archive and register available again)")
        self.paused_reason = ""

    # ================================================================ helpers
    async def _lock(self, mailbox_id) -> object | None:
        """Exclusive work on a mailbox across instances; None if another worker holds it."""
        con = await self.pool.acquire()
        try:
            ok = await con.fetchval("SELECT pg_try_advisory_lock($1, hashtext($2))", LOCK_NAMESPACE, str(mailbox_id))
        except Exception:
            await self.pool.release(con)
            raise
        if not ok:
            await self.pool.release(con)
            return None
        return con

    async def _unlock(self, con, mailbox_id) -> None:
        try:
            await con.execute("SELECT pg_advisory_unlock($1, hashtext($2))", LOCK_NAMESPACE, str(mailbox_id))
        finally:
            await self.pool.release(con)

    async def mailbox_key(self, mb: dict) -> str:
        async with self.pool.acquire() as con:
            key = await con.fetchval("SELECT archive_key FROM alice.mail_import_mailboxes WHERE mailbox_id = $1",
                                     mb["id"])
            if key:
                return key
            key = archive_key(mb["display_name"], mb["id"])
            await con.execute("INSERT INTO alice.mail_import_mailboxes (mailbox_id, archive_key) VALUES ($1, $2) "
                              "ON CONFLICT (mailbox_id) DO NOTHING", mb["id"], key)
            return await con.fetchval("SELECT archive_key FROM alice.mail_import_mailboxes WHERE mailbox_id = $1",
                                      mb["id"])

    async def _status(self, mb: dict, status: str, *, error: str | None = None, ok: bool = False,
                      next_in: float | None = None, key: str | None = None) -> None:
        async with self.pool.acquire() as con:
            count = None
            if key:
                count = await con.fetchval("SELECT count(DISTINCT source_id) FROM alice.source_locations "
                                           "WHERE mailbox = $1 AND present", key)
            await con.execute(
                """
                UPDATE alice.imap_mailboxes SET status = $2,
                       last_error = CASE WHEN $3::text IS NOT NULL THEN $3 WHEN $4 THEN NULL ELSE last_error END,
                       last_synced_at = CASE WHEN $4 THEN NOW() ELSE last_synced_at END,
                       mails_indexed = COALESCE($5, mails_indexed),
                       next_sync_at = CASE WHEN $6::float8 IS NULL THEN next_sync_at
                                           ELSE NOW() + make_interval(secs => $6::float8) END
                 WHERE id = $1
                """, mb["id"], status, error, ok, count, next_in)

    def _open(self, mb: dict) -> ImapSession:
        """Decrypt the password (memory only) and log in; raises ImapError with a plain cause."""
        try:
            password = decrypt_password(mb["password_enc"], self.s.mail_enc_key)
        except DecryptError as exc:
            raise ImapError(str(exc)) from None
        session = self.session_factory(mb, password)
        session.open()
        return session

    def _folders(self, session: ImapSession) -> list[tuple[str, str]]:
        """[(folder, role)]: INBOX and the folder flagged \\Sent; without flag the configured name (AK-3)."""
        listed = session.folders()
        names = {name for _, name in listed}
        out: list[tuple[str, str]] = []
        inbox = next((n for n in names if n.upper() == "INBOX"), None)
        if inbox:
            out.append((inbox, "inbox"))
        sent = next((n for flags, n in listed if "\\sent" in flags), None)
        if sent is None:
            fallback = self.s.sent_folder_fallback.lower()
            sent = next((n for n in names if n.lower() == fallback), None)
        if sent and sent != inbox:
            out.append((sent, "sent"))
        return out

    async def _known(self, key: str, folder: str) -> dict[int, dict]:
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT source_id, uid, message_id FROM alice.source_locations "
                                   "WHERE mailbox = $1 AND folder = $2 AND present AND uid IS NOT NULL", key, folder)
        return {r["uid"]: dict(r) for r in rows}

    # ================================================================ one mailbox
    async def sync_mailbox(self, mb: dict, *, nightly: bool = False) -> dict:
        """One tick of a mailbox: new mails first, then one package of history (AK-46/47)."""
        con = await self._lock(mb["id"])
        if con is None:
            return {"skipped": "busy"}
        try:
            return await self._sync_locked(mb, nightly=nightly)
        finally:
            await self._unlock(con, mb["id"])

    async def _sync_locked(self, mb: dict, *, nightly: bool = False) -> dict:
        key = await self.mailbox_key(mb)
        await self._status(mb, "syncing")
        try:
            session = await asyncio.to_thread(self._open, mb)
        except ImapError as exc:
            logger.warning("Mailbox %s: %s", key, exc)
            await self._status(mb, "error", error=str(exc), next_in=mb["sync_interval"] * 60, key=key)
            return {"error": str(exc)}
        try:
            result = await self._sync_session(mb, key, session)
            out = {"imported": result.imported, "linked": result.linked, "failed": result.failed,
                   "more": result.more, "folders": result.folders}
            if nightly:
                out["removal"] = await self._remove_gone(mb, key, session, result.folders)
        except Paused as exc:
            await self._status(mb, "active", next_in=self.s.tick_seconds)
            return {"paused": str(exc)}
        except ImapError as exc:
            logger.warning("Mailbox %s: %s", key, exc)
            await self._status(mb, "error", error=str(exc), next_in=mb["sync_interval"] * 60, key=key)
            return {"error": str(exc)}
        finally:
            await asyncio.to_thread(session.close)
        next_in = self.s.history_pause_seconds if result.more else mb["sync_interval"] * 60
        if result.failed and not result.more:
            next_in = mb["sync_interval"] * 60  # single failed mails: next tick, no tight loop
        await self._status(mb, "active", ok=True, next_in=next_in, key=key)
        if result.imported or result.linked:
            logger.info("Mailbox %s: %d imported, %d further locations, %d failed%s", key, result.imported,
                        result.linked, result.failed, ", more history pending" if result.more else "")
        return out

    async def _sync_session(self, mb: dict, key: str, session: ImapSession) -> SyncResult:
        result = SyncResult()
        folders = await asyncio.to_thread(self._folders, session)
        result.folders = [f for f, _ in folders]
        budget = self.s.batch_size
        plans = []
        for folder, role in folders:
            uidvalidity, uidnext = await asyncio.to_thread(session.examine, folder)
            state = await self._folder_state(mb, folder, role, uidvalidity, uidnext)
            if state["remap"]:
                await self._remap(session, key, folder)
            if mb["start_date"]:
                scope = await asyncio.to_thread(session.uids_since, mb["start_date"])
            else:
                scope = await asyncio.to_thread(session.uids_from, state["baseline_uid"] or uidnext or 1)
            known = await self._known(key, folder)
            unknown = sorted(set(scope) - set(known))
            top = max(known) if known else None
            new = [u for u in unknown if top is not None and u > top]
            history = sorted((u for u in unknown if top is None or u <= top), reverse=True)  # newest first
            plans.append((folder, new, history))
        # new mails of every folder before any history (AK-47)
        for folder, new, _ in plans:
            take, budget = new[:budget], budget - len(new[:budget])
            if len(take) < len(new):
                result.more = True
            await self._import_uids(session, key, folder, take, result, batch=len(take) > self.s.batch_threshold)
        for folder, _, history in plans:
            take, budget = history[:max(budget, 0)], max(budget, 0) - len(history[:max(budget, 0)])
            if len(take) < len(history):
                result.more = True
            await self._import_uids(session, key, folder, take, result, batch=len(take) > self.s.batch_threshold)
        return result

    async def _folder_state(self, mb: dict, folder: str, role: str, uidvalidity: int, uidnext: int | None) -> dict:
        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT uidvalidity, baseline_uid FROM alice.mail_import_folders "
                                     "WHERE mailbox_id = $1 AND folder = $2", mb["id"], folder)
            if row is None:
                baseline = None if mb["start_date"] else (uidnext or 1)
                await con.execute("INSERT INTO alice.mail_import_folders (mailbox_id, folder, role, uidvalidity, "
                                  "baseline_uid) VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
                                  mb["id"], folder, role, uidvalidity, baseline)
                return {"remap": False, "baseline_uid": baseline}
            remap = row["uidvalidity"] is not None and row["uidvalidity"] != uidvalidity
            baseline = row["baseline_uid"]
            if remap:
                # the old UIDs are meaningless now; without start date only mails arriving from now on
                baseline = None if baseline is None else (uidnext or 1)
                logger.warning("Folder %s: UIDVALIDITY changed, locations are matched again by Message-ID", folder)
            elif baseline is None and not mb["start_date"]:
                baseline = uidnext or 1  # start date removed: only mails arriving from now on
            await con.execute("UPDATE alice.mail_import_folders SET uidvalidity = $3, baseline_uid = $4, role = $5, "
                              "updated_at = NOW() WHERE mailbox_id = $1 AND folder = $2",
                              mb["id"], folder, uidvalidity, baseline, role)
            return {"remap": remap, "baseline_uid": baseline}

    async def _remap(self, session: ImapSession, key: str, folder: str) -> None:
        """EC-4: new UIDs for the known locations of this folder, matched by Message-ID; no mass deletion,
        no duplicates. Mails without Message-ID are matched by their fingerprint when they are imported."""
        uids = await asyncio.to_thread(session.all_uids)
        ids = await asyncio.to_thread(session.message_ids, uids) if uids else {}
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT source_id, message_id, uid FROM alice.source_locations "
                                   "WHERE mailbox = $1 AND folder = $2 AND present", key, folder)
        by_mid = {r["message_id"]: r for r in rows}
        for uid, mid in ids.items():
            row = by_mid.get(mid) if mid else None
            if row and row["uid"] != uid:
                await self.registry.add_location(row["source_id"], {"mailbox": key, "folder": folder, "uid": uid,
                                                                    "message_id": mid})

    async def _import_uids(self, session: ImapSession, key: str, folder: str, uids: list[int], result: SyncResult,
                           batch: bool) -> None:
        if not uids:
            return
        await asyncio.to_thread(session.examine, folder)  # the plan was made while other folders were open
        for uid in uids:
            try:
                fetched = await asyncio.to_thread(session.fetch, uid)
            except ConnectionLost:
                result.failed += 1
                raise  # the remaining mails follow in the next tick (AK-43)
            if fetched is None:
                continue  # gone meanwhile
            raw, received = fetched
            try:
                created = await self.import_raw(key, folder, uid, raw, received, batch=batch)
            except (Paused, RegistryUnavailable, ArchiveUnavailable) as exc:
                raise Paused(str(exc)) from exc
            except Exception as exc:
                result.failed += 1
                self.stats["failed"] += 1
                logger.warning("Mailbox %s, folder %s, UID %d not imported (next tick retries): %s", key, folder,
                               uid, exc.__class__.__name__ + (f": {exc}" if isinstance(exc, (RegistryError, RegistryConflict, OSError)) else ""))
                continue
            if created:
                result.imported += 1
                self.stats["imported"] += 1
            else:
                result.linked += 1
                self.stats["linked"] += 1

    # ================================================================ one mail
    def _captured(self, prep: mime.Prepared, received: datetime | None) -> datetime:
        """Mail date; missing or in the future → time of receipt on the server (EC-5)."""
        now = datetime.now(timezone.utc)
        if prep.date and prep.date <= now + FUTURE_TOLERANCE:
            return prep.date
        return received or now

    async def import_raw(self, key: str, folder: str, uid: int, raw: bytes, received: datetime | None, *,
                         batch: bool = False) -> bool:
        """Archive + register one mail. True if a new source was created."""
        prep = mime.prepare(raw)
        loc = {"mailbox": key, "folder": folder, "uid": uid, "message_id": prep.location_key}
        existing = await self.registry.find_by_hash(prep.hash)
        if existing:
            await self.registry.add_location(existing["id"], loc)
            await self._check_same(existing["id"], prep, raw)
            await self._ensure_archived(existing["id"], key, prep, raw, received, existing)
            return False
        captured = self._captured(prep, received)
        folder_rel = month_dir(key, captured.astimezone(self.s.tz))
        try:
            tmp = await asyncio.to_thread(self.archive.stage_attachments, folder_rel,
                                          [(a.filename, a.data) for a in prep.attachments])
        except OSError as exc:
            raise ArchiveUnavailable(f"Mail-Archiv nicht beschreibbar: {exc.strerror or exc}") from exc
        try:
            res = await self.registry.register(hash=prep.hash, title=prep.subject[:1000], location=loc,
                                               size=prep.size, captured=captured, batch=batch)
        except BaseException:
            await asyncio.to_thread(self.archive.discard, tmp)
            raise
        sid = res["id"]
        if not res.get("created"):
            # created meanwhile by another worker (other mailbox with the same mail): it archives
            await asyncio.to_thread(self.archive.discard, tmp)
            return False
        await self._finish_archive(sid, key, folder_rel, prep, raw, tmp)
        return True

    async def _finish_archive(self, sid: str, key: str, folder_rel: str, prep: mime.Prepared, raw: bytes,
                              tmp: str | None) -> None:
        att_rel = f"{folder_rel}/{sid}.attachments"
        eml_rel = f"{folder_rel}/{sid}.eml"
        eml = prep.archived_eml(f"{sid}.attachments", raw)
        await asyncio.to_thread(self.archive.commit_attachments, tmp, att_rel)
        await asyncio.to_thread(self.archive.write_new, eml_rel, eml)
        atts = [{"filename": a.filename, "mime_type": a.mime_type, "size": a.size, "path": f"{att_rel}/{a.filename}"}
                for a in prep.attachments]
        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO alice.mail_archive (source_id, archive_key, eml_path, attachments, broken, "
                              "size) VALUES ($1, $2, $3, $4::jsonb, $5, $6) ON CONFLICT (source_id) DO NOTHING",
                              sid, key, eml_rel, json.dumps(atts), prep.broken, prep.size)
        if prep.broken:
            logger.warning("Source %s: mail archived unchanged, %s", sid, prep.broken)

    async def _entry(self, sid: str) -> dict | None:
        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT source_id, archive_key, eml_path, attachments, broken, size "
                                     "FROM alice.mail_archive WHERE source_id = $1", sid)
        if not row:
            return None
        d = dict(row)
        if isinstance(d["attachments"], str):
            d["attachments"] = json.loads(d["attachments"])
        return d

    async def _check_same(self, sid: str, prep: mime.Prepared, raw: bytes) -> None:
        """EC-3: same Message-ID, different content → the first archived version stays; logged."""
        entry = await self._entry(sid)
        if entry and entry["size"] is not None and entry["size"] != prep.size and prep.hash.startswith("mid:"):
            logger.info("Source %s: same Message-ID with different content seen; the archived version stays", sid)

    async def _ensure_archived(self, sid: str, key: str, prep: mime.Prepared, raw: bytes,
                               received: datetime | None, source: dict | None = None) -> list[str]:
        """Put missing archive files of a known source back (never overwrite, AK-16, AK-52).
        Returns the relative paths written."""
        entry = await self._entry(sid)
        written: list[str] = []
        if entry is None:
            src = source or await self.registry.get_source(sid)
            first = next((l for l in src.get("locations") or [] if l.get("mailbox")), None)
            akey = first["mailbox"] if first else key
            captured = datetime.fromisoformat(src["captured"]) if isinstance(src.get("captured"), str) \
                else (src.get("captured") or self._captured(prep, received))
            folder_rel = month_dir(akey, captured.astimezone(self.s.tz))
            tmp = await asyncio.to_thread(self.archive.stage_attachments, folder_rel,
                                          [(a.filename, a.data) for a in prep.attachments])
            await self._finish_archive(sid, akey, folder_rel, prep, raw, tmp)
            return [f"{folder_rel}/{sid}.eml"]
        if not await asyncio.to_thread(self.archive.exists, entry["eml_path"]):
            att_dir = f"{entry['eml_path'].rsplit('/', 1)[-1][:-4]}.attachments"
            eml = prep.archived_eml(att_dir, raw) if not entry["broken"] else raw
            if await asyncio.to_thread(self.archive.write_new, entry["eml_path"], eml):
                written.append(entry["eml_path"])
        by_name = {a.filename: a for a in prep.attachments}
        for a in entry["attachments"]:
            if not await asyncio.to_thread(self.archive.exists, a["path"]) and a["filename"] in by_name:
                if await asyncio.to_thread(self.archive.write_new, a["path"], by_name[a["filename"]].data):
                    written.append(a["path"])
        if written:
            logger.info("Source %s: %d missing archive file(s) stored again", sid, len(written))
        return written

    # ================================================================ nightly
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
            return not await con.fetchval("SELECT EXISTS (SELECT 1 FROM alice.mail_import_runs WHERE kind = 'nightly' "
                                          "AND state = 'done' AND started_at >= $1)", slot)

    async def nightly(self, kind: str = "nightly") -> dict:
        """Reconcile every mailbox with the server (AK-33–39)."""
        con = await self.pool.acquire()
        try:
            if not await con.fetchval("SELECT pg_try_advisory_lock($1, 0)", NIGHTLY_LOCK):
                return {"skipped": "busy"}
            try:
                return await self._nightly(kind)
            finally:
                await con.execute("SELECT pg_advisory_unlock($1, 0)", NIGHTLY_LOCK)
        finally:
            await self.pool.release(con)

    async def _nightly(self, kind: str) -> dict:
        async with self.pool.acquire() as con:
            run_id = await con.fetchval("INSERT INTO alice.mail_import_runs (kind) VALUES ($1) RETURNING id", kind)
        summary: dict = {"mailboxes": {}, "deleted_mailboxes": {}}
        state = "done"
        try:
            await self.check_ready()
            summary["deleted_mailboxes"] = await self._remove_deleted_mailboxes()
            async with self.pool.acquire() as con:
                rows = await con.fetch(f"SELECT {MAILBOX_COLS} FROM alice.imap_mailboxes ORDER BY created_at, id")
            for mb in rows:
                mb = dict(mb)
                out = None
                for _ in range(60):  # wait for a running tick of this mailbox
                    out = await self.sync_mailbox(mb, nightly=True)
                    if out.get("skipped") != "busy":
                        break
                    await asyncio.sleep(5)
                key = await self.mailbox_key(mb)
                summary["mailboxes"][key] = out
                async with self.pool.acquire() as con:
                    await con.execute("UPDATE alice.mail_import_mailboxes SET last_nightly_at = NOW() "
                                      "WHERE mailbox_id = $1", mb["id"])
        except Paused as exc:
            state, summary["error"] = "failed", str(exc)
        except Exception as exc:
            logger.exception("Nightly run failed")
            state, summary["error"] = "failed", f"{exc.__class__.__name__}: {exc}"
        async with self.pool.acquire() as con:
            await con.execute("UPDATE alice.mail_import_runs SET state = $2, finished_at = NOW(), summary = $3::jsonb "
                              "WHERE id = $1", run_id, state, json.dumps(summary, default=str))
        logger.info("Nightly mail reconciliation %s: %s", state, json.dumps(summary, default=str)[:2000])
        return {"id": run_id, "state": state, **summary}

    async def _remove_deleted_mailboxes(self) -> dict:
        """AK-38: mailbox deleted in the settings → all its locations go, without the 20 % limit."""
        out = {}
        async with self.pool.acquire() as con:
            gone = await con.fetch("SELECT m.mailbox_id, m.archive_key FROM alice.mail_import_mailboxes m "
                                   "WHERE NOT EXISTS (SELECT 1 FROM alice.imap_mailboxes i WHERE i.id = m.mailbox_id)")
        for row in gone:
            async with self.pool.acquire() as con:
                locs = await con.fetch("SELECT source_id, folder, message_id FROM alice.source_locations "
                                       "WHERE mailbox = $1 AND present", row["archive_key"])
            removed, deleted = await self._remove(row["archive_key"], [dict(r) for r in locs])
            async with self.pool.acquire() as con:
                await con.execute("UPDATE alice.mail_import_mailboxes SET removed_at = NOW() WHERE mailbox_id = $1",
                                  row["mailbox_id"])
                await con.execute("DELETE FROM alice.mail_import_folders WHERE mailbox_id = $1", row["mailbox_id"])
            if locs:
                logger.info("Mailbox %s was deleted: %d locations removed, %d mails deleted", row["archive_key"],
                            removed, deleted)
            out[row["archive_key"]] = {"removed": removed, "deleted": deleted}
        return out

    async def _remove(self, key: str, locs: list[dict]) -> tuple[int, int]:
        removed = deleted = 0
        for loc in locs:
            try:
                res = await self.registry.remove_location(loc["source_id"], {
                    "mailbox": key, "folder": loc["folder"], "message_id": loc["message_id"]})
            except RegistryNotFound:
                continue
            removed += 1
            self.stats["removed"] += 1
            if res.get("deleted"):
                deleted += 1
        return removed, deleted

    async def _remove_gone(self, mb: dict, key: str, session: ImapSession, folders: list[str]) -> dict:
        """Locations whose mail is no longer in INBOX/sent (AK-33/34), with the 20 % guard (AK-36).
        An empty folder list removes nothing (AK-37)."""
        if not folders:
            return {"skipped": "Keine Ordner vom Server gemeldet: nichts entfernt"}
        on_server: dict[str, set[int]] = {}
        for folder in folders:
            await asyncio.to_thread(session.examine, folder)
            on_server[folder] = set(await asyncio.to_thread(session.all_uids))
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT source_id, folder, uid, message_id FROM alice.source_locations "
                                   "WHERE mailbox = $1 AND present", key)
        gone = [dict(r) for r in rows if r["folder"] not in on_server or r["uid"] not in on_server[r["folder"]]]
        known = len(rows)
        if gone and known and len(gone) * 100.0 / known > self.s.delete_limit_percent:
            logger.warning("Mailbox %s: %d of %d locations missing on the server (> %s %%), nothing removed",
                           key, len(gone), known, self.s.delete_limit_percent)
            return {"blocked": True, "missing": len(gone), "known": known,
                    "reason": f"{len(gone)} von {known} Fundorten fehlen (> {self.s.delete_limit_percent:g} %)"}
        removed, deleted = await self._remove(key, gone)
        return {"blocked": False, "removed": removed, "deleted": deleted, "known": known}

    # ================================================================ PROJ-120 levels 5 / 6
    async def _with_mailbox(self, mb: dict, fn, wait_seconds: float = 600):
        deadline = time.monotonic() + wait_seconds
        while True:
            con = await self._lock(mb["id"])
            if con is not None:
                break
            if time.monotonic() > deadline:
                raise ImapError("Postfach ist gerade in Arbeit")
            await asyncio.sleep(2)
        try:
            session = await asyncio.to_thread(self._open, mb)
            try:
                return await fn(session)
            finally:
                await asyncio.to_thread(session.close)
        finally:
            await self._unlock(con, mb["id"])

    async def reconcile_check(self) -> dict:
        """Level 5 IMAP ↔ register and level 6 register ↔ mail archive, read only (AK-51–53)."""
        imap_missing, notes = [], []
        async with self.pool.acquire() as con:
            mailboxes = [dict(r) for r in await con.fetch(f"SELECT {MAILBOX_COLS} FROM alice.imap_mailboxes "
                                                          "ORDER BY created_at, id")]
        for mb in mailboxes:
            key = await self.mailbox_key(mb)

            async def check(session, key=key, mb=mb):
                found = []
                for folder, _ in await asyncio.to_thread(self._folders, session):
                    await asyncio.to_thread(session.examine, folder)
                    async with self.pool.acquire() as con:
                        baseline = await con.fetchval("SELECT baseline_uid FROM alice.mail_import_folders "
                                                      "WHERE mailbox_id = $1 AND folder = $2", mb["id"], folder)
                    if mb["start_date"]:
                        scope = await asyncio.to_thread(session.uids_since, mb["start_date"])
                    elif baseline:
                        scope = await asyncio.to_thread(session.uids_from, baseline)
                    else:
                        scope = []
                    known = await self._known(key, folder)
                    found += [{"mailbox": key, "folder": folder, "uid": u} for u in sorted(set(scope) - set(known))]
                return found

            try:
                imap_missing += await self._with_mailbox(mb, check)
            except ImapError as exc:
                notes.append(f"Postfach {key} nicht geprüft: {exc}")
        archive_missing = await self._archive_gaps()
        return {"imap": {"missing": imap_missing, "notes": notes}, "archive": {"missing": archive_missing}}

    async def _archive_gaps(self) -> list[dict]:
        try:
            await asyncio.to_thread(self.archive.check)
        except ArchiveUnavailable as exc:
            raise Paused(str(exc)) from exc
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                """
                SELECT s.id, s.title, s.deleted, a.eml_path, a.attachments,
                       EXISTS (SELECT 1 FROM alice.source_locations l
                                WHERE l.source_id = s.id AND l.present AND l.uid IS NOT NULL) AS on_server
                  FROM alice.sources s LEFT JOIN alice.mail_archive a ON a.source_id = s.id
                 WHERE s.kind = 'email' ORDER BY s.id
                """)
        gaps = []
        for r in rows:
            missing = []
            if r["eml_path"] is None or not await asyncio.to_thread(self.archive.exists, r["eml_path"]):
                missing.append(("eml_missing", r["eml_path"]))
            atts = r["attachments"]
            atts = json.loads(atts) if isinstance(atts, str) else (atts or [])
            for a in atts:
                if not await asyncio.to_thread(self.archive.exists, a["path"]):
                    missing.append(("attachment_missing", a["path"]))
            for gap, path in missing:
                gaps.append({"gap": gap, "source_id": r["id"], "path": path, "on_server": r["on_server"],
                             "title": r["title"]})
        return gaps

    async def reconcile_repair(self, items: list[dict]) -> list[dict]:
        """Repairs of the levels 5/6: import missing mails, store missing archive files again."""
        results = []
        await self.check_ready()
        async with self.pool.acquire() as con:
            boxes = {r["archive_key"]: r["mailbox_id"] for r in await con.fetch(
                "SELECT archive_key, mailbox_id FROM alice.mail_import_mailboxes")}
            mbs = {r["id"]: dict(r) for r in await con.fetch(f"SELECT {MAILBOX_COLS} FROM alice.imap_mailboxes")}
        imports: dict[str, list[dict]] = {}
        rearchive: list[dict] = []
        for it in items:
            if it.get("type") == "mail_import":
                imports.setdefault(it["mailbox"], []).append(it)
            else:
                rearchive.append(it)
        for key, its in imports.items():
            mb = mbs.get(boxes.get(key))
            if not mb:
                results += [{**it, "repaired": False, "detail": "Postfach unbekannt"} for it in its]
                continue

            async def do_import(session, key=key, its=its):
                out = []
                by_folder: dict[str, list[dict]] = {}
                for it in its:
                    by_folder.setdefault(it["folder"], []).append(it)
                for folder, fits in by_folder.items():
                    await asyncio.to_thread(session.examine, folder)
                    for it in fits:
                        fetched = await asyncio.to_thread(session.fetch, int(it["uid"]))
                        if fetched is None:
                            out.append({**it, "repaired": False, "detail": "Mail nicht mehr auf dem Server"})
                            continue
                        created = await self.import_raw(key, folder, int(it["uid"]), fetched[0], fetched[1])
                        out.append({**it, "repaired": True, "detail": "nachgeholt" if created else "Fundort ergänzt"})
                return out

            try:
                results += await self._with_mailbox(mb, do_import)
            except ImapError as exc:
                results += [{**it, "repaired": False, "detail": str(exc)} for it in its]
        for it in rearchive:
            results.append(await self._rearchive(it, boxes, mbs))
        return results

    async def _rearchive(self, it: dict, boxes: dict, mbs: dict) -> dict:
        sid = it["source_id"]
        async with self.pool.acquire() as con:
            locs = await con.fetch("SELECT mailbox, folder, uid FROM alice.source_locations WHERE source_id = $1 "
                                   "AND present AND uid IS NOT NULL ORDER BY first_seen, id", sid)
        for loc in locs:
            mb = mbs.get(boxes.get(loc["mailbox"]))
            if not mb:
                continue

            async def fetch(session, loc=loc):
                await asyncio.to_thread(session.examine, loc["folder"])
                return await asyncio.to_thread(session.fetch, loc["uid"])

            try:
                fetched = await self._with_mailbox(mb, fetch)
            except ImapError as exc:
                return {**it, "repaired": False, "detail": str(exc)}
            if fetched is None:
                continue
            prep = mime.prepare(fetched[0])
            written = await self._ensure_archived(sid, loc["mailbox"], prep, fetched[0], fetched[1])
            return {**it, "repaired": bool(written), "detail": ", ".join(written) or "nichts fehlte mehr"}
        return {**it, "repaired": False, "detail": "Mail nicht mehr auf dem Server"}
