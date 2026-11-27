"""Mail attachments as sources (PROJ-124).

The real attachments of an imported mail (mail archive, PROJ-123) become sources of their own in the
register: one loop picks every mail whose stage `extract` finished after its attachments were last
handled (new mails first, then the stock in packages), registers each attachment with a recognised
extension (list of alice-file-detection, PROJ-116) with the archive file as location and the mail as
parent (known hash: further location + parent), writes the source ids and links into the mail
markdown and follows renamed markdowns. Attachments that are not registered are counted per
extension and mailbox. Nothing is copied, the archive is only read.

Only one instance works at a time (PostgreSQL advisory lock); the hash uniqueness of the register
prevents duplicates in any case."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import posixpath
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import httpx

from . import mailmd
from .archive import Archive
from .config import Settings
from .registry import RegistryClient, RegistryConflict, RegistryError, RegistryNotFound, RegistryUnavailable

logger = logging.getLogger("alice-mail-import.attachments")

LOCK_KEY = (1232, 0)  # pg advisory lock of the attachment loop
HASH_CHUNK = 1024 * 1024
LINK_BACKOFF_SECONDS = [60, 300, 1800, 7200, 43200]  # like the register (PROJ-115)
LINK_FOLLOW_LIMIT = 100
MIN_SUMMARY_RETENTION_DAYS = 30


class Paused(Exception):
    """Archive, register or detection list not available: stop without changes (AK-39, AK-40)."""


class MailPaused(Exception):
    """One attachment file of this mail is not readable: the mail waits, nothing changed for it."""


def extension(name: str) -> str:
    base = posixpath.basename(name or "")
    if "." not in base.strip("."):
        return ""
    return base.rsplit(".", 1)[1].lower()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(HASH_CHUNK):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _json(value):
    return json.loads(value) if isinstance(value, str) else (value or [])


def summary_of(counter: Counter, empty: int) -> dict:
    """Attachments not processed: total, per extension, per mailbox (per extension), of which empty."""
    by_ext: Counter = Counter()
    by_box: dict[str, Counter] = defaultdict(Counter)
    for (box, ext), n in counter.items():
        by_ext[ext] += n
        by_box[box][ext] += n
    return {"total": sum(by_ext.values()), "empty": empty,
            "by_extension": dict(sorted(by_ext.items(), key=lambda kv: (-kv[1], kv[0]))),
            "by_mailbox": {box: dict(sorted(c.items())) for box, c in sorted(by_box.items())}}


class DetectionClient:
    """The detection list of alice-file-detection (`GET /extensions`), the only place it is maintained."""

    def __init__(self, base_url: str, refresh_seconds: float = 300, client: httpx.AsyncClient | None = None):
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=10)
        self.refresh = refresh_seconds
        self.cached: dict[str, str] | None = None
        self.fetched = float("-inf")

    async def close(self) -> None:
        await self.http.aclose()

    async def extensions(self) -> dict[str, str]:
        if self.cached is not None and time.monotonic() - self.fetched < self.refresh:
            return self.cached
        try:
            r = await self.http.get("/extensions")
            r.raise_for_status()
            exts = r.json()["extensions"]
            if not isinstance(exts, dict) or not exts:
                raise ValueError("leere Erkennungsliste")
            self.cached = {str(k).lower().lstrip("."): str(v) for k, v in exts.items()}
            self.fetched = time.monotonic()
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            if self.cached is None:
                raise Paused(f"Erkennungsliste der Datei-Erkennung nicht abrufbar ({exc.__class__.__name__})") from None
            logger.warning("Detection list not refreshed (%s); using the last known list", exc.__class__.__name__)
            self.fetched = time.monotonic() - self.refresh + 60  # retry in a minute
        return self.cached


class AttachmentWorker:
    def __init__(self, settings: Settings, pool, registry: RegistryClient, archive: Archive,
                 detection: DetectionClient):
        self.s = settings
        self.pool = pool
        self.registry = registry
        self.archive = archive
        self.detection = detection
        self.poll = settings.attachment_poll_seconds
        self.last_tick = time.monotonic()
        self.paused_reason = ""
        self.stats = {"mails": 0, "registered": 0, "new_sources": 0, "not_processed": 0, "links_written": 0,
                      "links_failed": 0, "paused_mails": 0}

    # ================================================================ loop
    async def run(self) -> None:
        while True:
            self.last_tick = time.monotonic()
            try:
                n = await self.step()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("attachment loop step failed")
                n = 0
            if not n:
                await asyncio.sleep(self.poll)

    def _pause(self, reason: str) -> None:
        if reason != self.paused_reason:
            logger.warning("Attachment registration paused: %s", reason)
        self.paused_reason = reason

    async def _ready(self) -> dict[str, str]:
        exts = await self.detection.extensions()
        if not await asyncio.to_thread(os.path.isdir, self.archive.root):
            raise Paused(f"Mail-Archiv {self.archive.root} nicht vorhanden (NAS nicht eingebunden?)")
        ok, why = await self.registry.available()
        if not ok:
            raise Paused(why)
        if self.paused_reason:
            logger.info("Attachment registration continues")
        self.paused_reason = ""
        return exts

    async def step(self) -> int:
        """One tick: due mails (newest extract first, at most one package), then link follow-up."""
        async with self.pool.acquire() as con:
            if not await con.fetchval("SELECT pg_try_advisory_lock($1, $2)", *LOCK_KEY):
                return 0  # another instance works (AK-8)
            try:
                return await self._step()
            finally:
                await con.execute("SELECT pg_advisory_unlock($1, $2)", *LOCK_KEY)

    async def _step(self) -> int:
        started = datetime.now(timezone.utc)
        try:
            exts = await self._ready()
            mails = await self._due(self.s.attachment_batch_size, sorted(exts))
            batch = len(mails) > self.s.batch_threshold
            counter: Counter = Counter()
            empty = [0]
            handled = 0
            try:
                for m in mails:
                    if await self.process_mail(m, exts, batch=batch, counter=counter, empty=empty):
                        handled += 1
            finally:
                if batch:
                    try:
                        await self.registry.flush()
                    except (RegistryUnavailable, RegistryError) as exc:
                        logger.warning("Batch commit not closed now (%s); the register closes it by time", exc)
                if handled:
                    await self._store_run("tick", started, {"mails": handled, **summary_of(counter, empty[0])})
            followed = await self.follow_links()
        except Paused as exc:
            self._pause(str(exc))
            return 0
        return len(mails) + followed

    async def _due(self, limit: int, recognised: list[str]) -> list[dict]:
        """Mails whose extract finished after their attachments were handled, and mails with an attachment
        whose extension was added to the detection list meanwhile (AK-4)."""
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                """
                SELECT a.source_id, a.archive_key, a.attachments, s.captured, ss.updated_at AS extract_at
                  FROM alice.mail_archive a
                  JOIN alice.sources s ON s.id = a.source_id
                  JOIN alice.source_stages ss ON ss.source_id = a.source_id AND ss.stage = 'extract'
                                             AND ss.state = 'done'
                  LEFT JOIN alice.mail_attachment_mails m ON m.mail_id = a.source_id
                 WHERE jsonb_array_length(a.attachments) > 0
                   AND (m.processed_at IS NULL OR m.processed_at < ss.updated_at
                        OR EXISTS (SELECT 1 FROM alice.mail_attachments x WHERE x.mail_id = a.source_id
                                      AND x.status = 'unsupported' AND x.extension = ANY($2::text[])))
                   AND (m.next_try_at IS NULL OR m.next_try_at <= NOW())
                 ORDER BY ss.updated_at DESC, a.source_id
                 LIMIT $1
                """, limit, recognised)
        return [dict(r) for r in rows]

    async def _mail_row(self, mail_id: str) -> dict | None:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "SELECT a.source_id, a.archive_key, a.attachments, s.captured, ss.updated_at AS extract_at "
                "FROM alice.mail_archive a JOIN alice.sources s ON s.id = a.source_id "
                "LEFT JOIN alice.source_stages ss ON ss.source_id = a.source_id AND ss.stage = 'extract' "
                "AND ss.state = 'done' WHERE a.source_id = $1", mail_id)
        return dict(row) if row else None

    # ================================================================ one mail
    async def _inspect(self, mail: dict, exts: dict[str, str]) -> list[dict]:
        """Every attachment with extension, kind, status and hash; MailPaused if a registrable file is not
        readable (nothing registered for this mail then, AK-39)."""
        async with self.pool.acquire() as con:
            known = {r["position"]: dict(r) for r in await con.fetch(
                "SELECT position, path, size, mtime_ns, hash FROM alice.mail_attachments WHERE mail_id = $1",
                mail["source_id"])}
        out = []
        for i, a in enumerate(_json(mail["attachments"])):
            ext = extension(a.get("filename") or a.get("path") or "")
            item = {"position": i, "filename": a.get("filename") or posixpath.basename(a["path"]),
                    "path": a["path"], "extension": ext, "kind": exts.get(ext), "size": a.get("size"),
                    "mtime_ns": None, "hash": None}
            if not a.get("size"):
                item["status"] = "empty"  # AK-13: counted, not registered
            elif item["kind"] is None:
                item["status"] = "unsupported"  # AK-12, EC-7
            else:
                full = self.archive.path(a["path"])
                try:
                    st = await asyncio.to_thread(os.stat, full)
                    item["size"], item["mtime_ns"] = st.st_size, st.st_mtime_ns
                    if item["size"] == 0:
                        item["status"] = "empty"
                        out.append(item)
                        continue
                    k = known.get(i)
                    if k and k["path"] == a["path"] and k["hash"] and (k["size"], k["mtime_ns"]) == (
                            item["size"], item["mtime_ns"]):
                        item["hash"] = k["hash"]  # archive files never change (PROJ-123)
                    else:
                        item["hash"] = await asyncio.to_thread(sha256_file, full)
                except OSError as exc:
                    raise MailPaused(f"Anhangsdatei nicht lesbar ({exc.strerror or exc.__class__.__name__}): "
                                     f"{a['path']}") from None
                item["status"] = "registered"
            out.append(item)
        return out

    async def process_mail(self, mail: dict, exts: dict[str, str], *, batch: bool = False,
                           counter: Counter | None = None, empty: list | None = None) -> bool:
        """Register the attachments of one mail and write the references. False if the mail waits
        (file not readable, register refuses). Paused propagates (register away: nothing lost)."""
        mid = mail["source_id"]
        try:
            items = await self._inspect(mail, exts)
        except MailPaused as exc:
            await self._mail_paused(mid, str(exc))
            return False
        captured = mail["captured"] or datetime.now(timezone.utc)
        for it in items:
            if it["status"] != "registered":
                continue
            modified = datetime.fromtimestamp(it["mtime_ns"] / 1e9, timezone.utc) if it["mtime_ns"] else None
            try:
                r = await self.registry.register_attachment(
                    kind=it["kind"], hash=it["hash"], title=it["filename"], path=self.archive.path(it["path"]),
                    size=it["size"], modified=modified, captured=captured, parent=mid, batch=batch)
            except RegistryUnavailable as exc:
                raise Paused(str(exc)) from None
            except (RegistryError, RegistryConflict, RegistryNotFound) as exc:
                logger.warning("Register refused attachment %d of mail %s: %s", it["position"], mid, str(exc)[:300])
                await self._mail_paused(mid, f"Register lehnt Anhang ab: {str(exc)[:500]}")
                return False
            it["source_id"] = r["id"]
            self.stats["registered"] += 1
            if r.get("created"):
                self.stats["new_sources"] += 1
        await self._save_items(mid, items)
        for it in items:
            if it["status"] != "registered" and counter is not None:
                counter[(mail["archive_key"], it["extension"] or "(ohne)")] += 1
                self.stats["not_processed"] += 1
                if it["status"] == "empty" and empty is not None:
                    empty[0] += 1
        await self.write_links(mid, batch=batch)
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO alice.mail_attachment_mails (mail_id, processed_at) VALUES ($1, $2) "
                "ON CONFLICT (mail_id) DO UPDATE SET processed_at = EXCLUDED.processed_at, next_try_at = NULL, "
                "pause_reason = NULL, updated_at = NOW()",
                mid, mail["extract_at"] or datetime.now(timezone.utc))
        self.stats["mails"] += 1
        logger.info("Mail %s: %d attachment(s) registered, %d not processed", mid,
                    sum(it["status"] == "registered" for it in items),
                    sum(it["status"] != "registered" for it in items))
        return True

    async def _mail_paused(self, mid: str, reason: str) -> None:
        self.stats["paused_mails"] += 1
        logger.warning("Mail %s waits: %s", mid, reason)
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO alice.mail_attachment_mails (mail_id, next_try_at, pause_reason) "
                "VALUES ($1, NOW() + make_interval(secs => $2::float8), $3) "
                "ON CONFLICT (mail_id) DO UPDATE SET next_try_at = EXCLUDED.next_try_at, "
                "pause_reason = EXCLUDED.pause_reason, updated_at = NOW()",
                mid, float(self.s.attachment_pause_seconds), reason[:1000])

    async def _save_items(self, mid: str, items: list[dict]) -> None:
        async with self.pool.acquire() as con, con.transaction():
            for it in items:
                await con.execute(
                    """
                    INSERT INTO alice.mail_attachments (mail_id, position, filename, path, extension, size, mtime_ns,
                                                        hash, status, source_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (mail_id, position) DO UPDATE SET filename = EXCLUDED.filename,
                        path = EXCLUDED.path, extension = EXCLUDED.extension, size = EXCLUDED.size,
                        mtime_ns = EXCLUDED.mtime_ns, hash = EXCLUDED.hash, status = EXCLUDED.status,
                        source_id = EXCLUDED.source_id,
                        linked_path = CASE WHEN alice.mail_attachments.source_id IS NOT DISTINCT FROM
                                      EXCLUDED.source_id THEN alice.mail_attachments.linked_path END,
                        updated_at = NOW()
                    """, mid, it["position"], it["filename"], it["path"], it["extension"], it["size"],
                    it["mtime_ns"], it["hash"], it["status"], it.get("source_id"))
            await con.execute("DELETE FROM alice.mail_attachments WHERE mail_id = $1 AND position >= $2",
                              mid, len(items))

    # ================================================================ references in the mail
    async def known_links(self, mid: str, mail_path: str) -> dict:
        """Absolute archive path → (attachment source id, markdown path relative to the mail markdown)."""
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT ma.path, ma.source_id, s.path AS md_path FROM alice.mail_attachments ma "
                "JOIN alice.sources s ON s.id = ma.source_id WHERE ma.mail_id = $1 AND ma.status = 'registered' "
                "ORDER BY ma.position", mid)
        return {self.archive.path(r["path"]): (r["source_id"], posixpath.relpath(r["md_path"],
                                                                                 posixpath.dirname(mail_path)))
                for r in rows}

    async def write_links(self, mid: str, batch: bool = False) -> bool:
        """`attachments[].id` + links in the section „Anhänge“ of the mail markdown (AK-18–22). Nothing is
        written if everything is in place (AK-7). Errors (manual, locked, not writable) → retry with
        backoff, event at the mail; the registrations stay (spec „Fehler“)."""
        try:
            doc = await self.registry.read_document(mid)
        except RegistryUnavailable as exc:
            raise Paused(str(exc)) from None
        except (RegistryConflict, RegistryNotFound, RegistryError) as exc:
            await self._link_failed(mid, f"Mail-Markdown nicht lesbar: {str(exc)[:300]}")
            return False
        fm, content, mail_path = doc.get("frontmatter") or {}, doc.get("content") or "", doc["path"]
        links = await self.known_links(mid, mail_path)
        manual = [m for m in fm.get("manual") or [] if isinstance(m, str)]
        current = fm.get("attachments") if isinstance(fm.get("attachments"), list) else []
        wanted = mailmd.with_ids([a for a in current if isinstance(a, dict)], {p: v[0] for p, v in links.items()})
        section = mailmd.attachment_section(wanted, {p: v[1] for p, v in links.items()}) if wanted else None
        new_content = mailmd.replace_section(content, section) if section else content
        content_manual = "content" in manual
        if "attachments" in manual and wanted != current:
            await self._link_failed(mid, "Feld attachments ist von Hand geschützt (manual): Quell-ids der "
                                         "Anhänge nicht nachgetragen")
            return False
        if wanted == current and (content_manual or new_content == content):
            await self._links_ok(mid, mail_path)
            return True
        try:
            res = await self.registry.write_links(mid, fields={} if wanted == current else {"attachments": wanted},
                                                  content=None if content_manual else new_content, batch=batch)
        except RegistryUnavailable as exc:
            raise Paused(str(exc)) from None
        except (RegistryConflict, RegistryNotFound, RegistryError) as exc:
            await self._link_failed(mid, f"Mail-Markdown nicht schreibbar: {str(exc)[:300]}")
            return False
        self.stats["links_written"] += 1
        await self._links_ok(mid, res.get("path") or mail_path)
        return True

    async def _links_ok(self, mid: str, mail_path: str) -> None:
        async with self.pool.acquire() as con, con.transaction():
            await con.execute(
                "INSERT INTO alice.mail_attachment_mails (mail_id, links_ok, mail_path) VALUES ($1, TRUE, $2) "
                "ON CONFLICT (mail_id) DO UPDATE SET links_ok = TRUE, link_error = NULL, link_attempts = 0, "
                "link_retry_at = NULL, mail_path = EXCLUDED.mail_path, updated_at = NOW()", mid, mail_path)
            await con.execute(
                "UPDATE alice.mail_attachments ma SET linked_path = s.path FROM alice.sources s "
                "WHERE ma.mail_id = $1 AND s.id = ma.source_id AND ma.linked_path IS DISTINCT FROM s.path", mid)

    async def _link_failed(self, mid: str, error: str) -> None:
        self.stats["links_failed"] += 1
        async with self.pool.acquire() as con:
            attempts = await con.fetchval(
                """
                INSERT INTO alice.mail_attachment_mails (mail_id, links_ok, link_error, link_attempts, link_retry_at)
                VALUES ($1, FALSE, $2, 1, NOW() + make_interval(secs => $3::int))
                ON CONFLICT (mail_id) DO UPDATE SET links_ok = FALSE, link_error = EXCLUDED.link_error,
                    link_attempts = alice.mail_attachment_mails.link_attempts + 1,
                    link_retry_at = NOW() + make_interval(secs => ($4::int[])[
                        LEAST(alice.mail_attachment_mails.link_attempts + 1, cardinality($4::int[]))]),
                    updated_at = NOW()
                RETURNING link_attempts
                """, mid, error[:2000], LINK_BACKOFF_SECONDS[0], LINK_BACKOFF_SECONDS)
        logger.warning("References in mail %s not written (attempt %d): %s", mid, attempts, error)
        if attempts == 1:
            try:
                await self.registry.event(mid, "warning", "attachment_links_failed",
                                          f"Verweise auf die Anhangs-Quellen nicht nachgetragen: {error}")
            except Exception as exc:
                logger.warning("Event for mail %s not stored: %s", mid, exc.__class__.__name__)

    async def follow_links(self) -> int:
        """Renamed attachment markdown (title change, AK-20) or moved mail markdown, and references whose
        retry is due → write the section again."""
        async with self.pool.acquire() as con:
            ids = [r["mail_id"] for r in await con.fetch(
                """
                SELECT m.mail_id FROM alice.mail_attachment_mails m
                  JOIN alice.sources ms ON ms.id = m.mail_id
                 WHERE m.processed_at IS NOT NULL AND (
                       (NOT m.links_ok AND (m.link_retry_at IS NULL OR m.link_retry_at <= NOW()))
                    OR (m.links_ok AND EXISTS (
                           SELECT 1 FROM alice.mail_attachments ma JOIN alice.sources s ON s.id = ma.source_id
                            WHERE ma.mail_id = m.mail_id
                              AND (s.path IS DISTINCT FROM ma.linked_path OR ms.path IS DISTINCT FROM m.mail_path))))
                 ORDER BY m.mail_id LIMIT $1
                """, LINK_FOLLOW_LIMIT)]
        for mid in ids:
            await self.write_links(mid)
        return len(ids)

    # ================================================================ summaries (AK-34)
    async def _store_run(self, kind: str, started: datetime, summary: dict) -> None:
        keep = max(MIN_SUMMARY_RETENTION_DAYS, self.s.attachment_summary_retention_days)
        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO alice.mail_attachment_runs (kind, started_at, finished_at, summary) "
                              "VALUES ($1, $2, NOW(), $3::jsonb)", kind, started, json.dumps(summary))
            await con.execute("DELETE FROM alice.mail_attachment_runs "
                              "WHERE started_at < NOW() - make_interval(days => $1::int)", keep)

    async def runs(self, limit: int = 50, kind: str | None = None) -> list[dict]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT id, kind, started_at, finished_at, summary FROM alice.mail_attachment_runs "
                "WHERE ($2::text IS NULL OR kind = $2) ORDER BY started_at DESC, id DESC LIMIT $1", limit, kind)
        return [{"id": r["id"], "kind": r["kind"], "started_at": r["started_at"].isoformat(),
                 "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
                 "summary": _json(r["summary"]) or {}} for r in rows]

    # ================================================================ level 7 (PROJ-120)
    async def reconcile_check(self) -> dict:
        """Level 7 „Mail ↔ Anhangs-Quellen“, read only: every attachment with a recognised extension has a
        source (parents contain the mail, archive path is a location) and its id in the mail markdown.
        Missing registrations → repair `attachment_register`; missing or changed archive files are only
        reported (AK-32, EC-4). Also stores the summary of the attachments not processed (all mails)."""
        started = datetime.now(timezone.utc)
        try:
            exts = await self.detection.extensions()
        except Paused as exc:
            return {"missing": [], "notes": [f"Ebene 7 nicht geprüft: {exc}"]}
        if not await asyncio.to_thread(os.path.isdir, self.archive.root):
            return {"missing": [], "notes": [f"Ebene 7 nicht geprüft: Mail-Archiv {self.archive.root} nicht vorhanden"]}
        root = self.archive.root
        async with self.pool.acquire() as con:
            mails = await con.fetch(
                "SELECT a.source_id, a.archive_key, a.attachments, s.title, m.processed_at, m.links_ok "
                "FROM alice.mail_archive a JOIN alice.sources s ON s.id = a.source_id "
                "LEFT JOIN alice.mail_attachment_mails m ON m.mail_id = a.source_id "
                "WHERE jsonb_array_length(a.attachments) > 0 ORDER BY a.source_id")
            rows = await con.fetch(
                """
                SELECT ma.mail_id, ma.position, ma.path, ma.size, ma.mtime_ns, ma.hash, ma.status, ma.source_id,
                       src.id IS NOT NULL AS source_exists,
                       EXISTS (SELECT 1 FROM alice.source_parents p
                                WHERE p.source_id = ma.source_id AND p.parent_id = ma.mail_id) AS has_parent,
                       EXISTS (SELECT 1 FROM alice.source_locations l WHERE l.source_id = ma.source_id
                                  AND l.present AND l.path = $1 || '/' || ma.path) AS has_location
                  FROM alice.mail_attachments ma LEFT JOIN alice.sources src ON src.id = ma.source_id
                """, root.rstrip("/"))
        known = {(r["mail_id"], r["position"]): dict(r) for r in rows}
        counter: Counter = Counter()
        empty = 0
        gaps: list[dict] = []
        checked = 0
        for m in mails:
            mid = m["source_id"]
            for i, a in enumerate(_json(m["attachments"])):
                ext = extension(a.get("filename") or a.get("path") or "")
                if not a.get("size") or exts.get(ext) is None:
                    counter[(m["archive_key"], ext or "(ohne)")] += 1
                    empty += 0 if a.get("size") else 1
                    continue
                checked += 1
                base = {"mail_id": mid, "title": m["title"], "path": self.archive.path(a["path"]),
                        "filename": a.get("filename")}
                k = known.get((mid, i))
                full = self.archive.path(a["path"])
                try:
                    st = await asyncio.to_thread(os.stat, full)
                except OSError:
                    gaps.append({**base, "gap": "attachment_file_missing", "source_id": k and k["source_id"],
                                 "repair": None})
                    continue
                ok = (k and k["status"] == "registered" and k["source_exists"] and k["has_parent"]
                      and k["has_location"] and k["path"] == a["path"])
                if not ok:
                    gaps.append({**base, "gap": "attachment_unregistered", "source_id": k and k["source_id"],
                                 "repair": "attachment_register"})
                    continue
                if (st.st_size, st.st_mtime_ns) != (k["size"], k["mtime_ns"]):
                    try:
                        h = await asyncio.to_thread(sha256_file, full)
                    except OSError:
                        h = None
                    if h is not None and h != k["hash"]:
                        gaps.append({**base, "gap": "attachment_changed", "source_id": k["source_id"], "repair": None})
                        continue
                if not m["links_ok"]:
                    gaps.append({**base, "gap": "attachment_reference_missing", "source_id": k["source_id"],
                                 "repair": "attachment_register"})
        await self._store_run("reconcile", started, {"mails": len(mails), **summary_of(counter, empty)})
        return {"checked": checked, "missing": gaps, "notes": []}

    async def reconcile_repair(self, mail_ids: list[str]) -> list[dict]:
        """Register the attachments of these mails now (under the lock of the loop)."""
        exts = await self._ready()
        results = []
        async with self.pool.acquire() as con:
            await con.execute("SELECT pg_advisory_lock($1, $2)", *LOCK_KEY)
            try:
                for mid in dict.fromkeys(mail_ids):
                    mail = await self._mail_row(mid)
                    if mail is None:
                        results.append({"type": "attachment_register", "source_id": mid, "repaired": False,
                                        "detail": "kein Archiv-Eintrag der Mail"})
                        continue
                    ok = await self.process_mail(mail, exts)
                    if ok:
                        async with self.pool.acquire() as c2:
                            row = await c2.fetchrow("SELECT links_ok, link_error FROM alice.mail_attachment_mails "
                                                    "WHERE mail_id = $1", mid)
                        ok = bool(row and row["links_ok"])
                        detail = "Anhänge registriert" if ok else f"Verweise offen: {row['link_error'] if row else ''}"
                    else:
                        async with self.pool.acquire() as c2:
                            detail = await c2.fetchval("SELECT pause_reason FROM alice.mail_attachment_mails "
                                                       "WHERE mail_id = $1", mid) or "nicht registriert"
                    results.append({"type": "attachment_register", "source_id": mid, "repaired": ok, "detail": detail})
            finally:
                await con.execute("SELECT pg_advisory_unlock($1, $2)", *LOCK_KEY)
        return results
