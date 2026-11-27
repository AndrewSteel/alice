"""Work loops of alice-image-processing.

- Describer (stage `extract` of images): claim → original → EXIF + vision → one write → done.
  At most `concurrency` images at the same time (AK-34). Order per round: images triggered one by one,
  new images, then the backlog (only when released, AK-31/32/33).
- Locator (stage `locate`): claim → GPS → place from the old Weaviate or Geoapify → write → done.
  One image after the other; new images before the backlog, regardless of the backlog release.

Both write the title: after its own write each one reads the markdown again and adds the place to the
title if the other step finished in between (AK-29), so the order of the two does not matter.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import document
from .config import Settings
from .errors import PermanentError, TransientError
from .geo import Geoapify, OldWeaviate, WeaviateUnavailable
from .imaging import prepare, read_exif
from .registry import (DESCRIBE, LOCATE, RegistryClient, RegistryConflict, RegistryError, RegistryNotFound,
                       RegistryUnavailable)
from .vision import VisionClient, VisionUnavailable

logger = logging.getLogger("alice-image-processing")

FOUND, MISSING, NAS_DOWN = "found", "missing", "nas_down"


class Paused(Exception):
    """Work given back without a failed attempt."""


class Base:
    name = ""
    stage = ""

    def __init__(self, settings: Settings, registry: RegistryClient, store):
        self.s = settings
        self.registry = registry
        self.store = store
        self.registry_down_since: float | None = None
        self.registry_reason = ""
        self.repo_paused_reason = ""
        self.db_down_since: float | None = None
        self.db_reason = ""
        self.nas_paused_until = 0.0
        self.nas_reason = ""
        self.last_tick = time.monotonic()
        self.stats = {"done": 0, "skipped": 0, "failed": 0, "failed_permanent": 0, "released": 0, "discarded": 0}

    # ---------------------------------------------------------------- health
    def health(self) -> tuple[list[str], list[str]]:
        errors, warnings = [], []
        for since, reason in ((self.registry_down_since, self.registry_reason), (self.db_down_since, self.db_reason)):
            if since is not None:
                (errors if time.monotonic() - since >= self.s.registry_grace_seconds else warnings).append(
                    f"{self.name} pausiert: {reason}")
        if time.monotonic() - self.last_tick > max(120.0, 3 * self.s.poll_seconds):
            errors.append(f"{self.name}: Arbeitsschleife läuft nicht")
        if self.repo_paused_reason:
            warnings.append(f"{self.name}: Register pausiert: {self.repo_paused_reason}")
        if self.nas_paused_until > time.monotonic():
            warnings.append(f"{self.name}: NAS nicht erreichbar, pausiert: {self.nas_reason}")
        return errors, warnings

    def _registry_down(self, exc: Exception) -> None:
        if self.registry_down_since is None:
            self.registry_down_since = time.monotonic()
            logger.warning("%s: source register unavailable, paused: %s", self.name, exc)
        self.registry_reason = str(exc)

    def _registry_up(self) -> None:
        if self.registry_down_since is not None:
            logger.info("%s: source register reachable again, continuing", self.name)
        self.registry_down_since = None
        self.registry_reason = ""

    def _db_down(self, exc: Exception) -> None:
        if self.db_down_since is None:
            self.db_down_since = time.monotonic()
            logger.warning("%s: PostgreSQL unavailable, paused: %s", self.name, exc)
        self.db_reason = f"PostgreSQL nicht erreichbar ({exc.__class__.__name__})"

    def _db_up(self) -> None:
        if self.db_down_since is not None:
            logger.info("%s: PostgreSQL reachable again", self.name)
        self.db_down_since = None
        self.db_reason = ""

    def _claimed(self, res: dict) -> list[dict] | None:
        """Items of a claim answer; None while the register is paused (repo unavailable)."""
        if res.get("paused"):
            if self.repo_paused_reason != res.get("reason"):
                logger.warning("%s: register paused (%s); waiting", self.name, res.get("reason"))
            self.repo_paused_reason = res.get("reason") or "pausiert"
            return None
        self.repo_paused_reason = ""
        return res.get("items") or []

    # ---------------------------------------------------------------- originals on the NAS
    def _share(self, path: str) -> str | None:
        root = self.s.nas_root.rstrip("/")
        if not path.startswith(root + "/"):
            return None
        first = path[len(root) + 1:].split("/", 1)[0]
        return f"{root}/{first}" if first else None

    def _share_reachable(self, path: str) -> bool:
        share = self._share(path)
        if share is None:  # outside the NAS root: judge by the parent folder
            return os.path.isdir(os.path.dirname(path))
        try:
            return os.path.isdir(share) and bool(os.listdir(share))  # an empty mount point = share missing
        except OSError:
            return False

    def find(self, paths: list[str]) -> tuple[str, str | None]:
        """First readable location; otherwise NAS_DOWN if a share is missing, else MISSING."""
        for p in paths:
            if os.path.isfile(p) and os.access(p, os.R_OK):
                return FOUND, p
        if any(not self._share_reachable(p) for p in paths):
            return NAS_DOWN, None
        return MISSING, None

    async def original(self, sid: str, token: str) -> tuple[dict, str, list[str]]:
        """(register entry, readable path, all present paths); Paused if work went back (AK-38)."""
        try:
            src = await self.registry.get_source(sid)
        except Exception as exc:
            logger.warning("Source %s could not be read from the register: %s", sid, exc)
            await self.release(sid, token)
            raise Paused() from None
        paths = [loc["path"] for loc in src.get("locations", []) if loc.get("present") and loc.get("path")]
        state, path = await asyncio.to_thread(self.find, paths)
        if state == FOUND:
            return src, path, paths
        await self.not_found(sid, token, state)
        raise Paused()

    async def not_found(self, sid: str, token: str, state: str) -> None:
        if state == NAS_DOWN:
            self.nas_reason = "Freigabe des Originals fehlt"
            if self.nas_paused_until <= time.monotonic():
                logger.warning("%s: NAS share of %s not reachable; work released, pausing for %ss", self.name, sid,
                               self.s.nas_retry_seconds)
            self.nas_paused_until = time.monotonic() + self.s.nas_retry_seconds
            await self.release(sid, token)
        else:  # the file detection (PROJ-116) decides whether the source is gone; no failed attempt
            logger.info("%s: original of %s not found although the share is reachable; released", self.name, sid)
            await self.release(sid, token, self.s.missing_retry_seconds)

    async def os_error(self, sid: str, token: str, paths: list[str], exc: OSError) -> str:
        state, _ = await asyncio.to_thread(self.find, paths)
        if state != FOUND:
            await self.not_found(sid, token, state)
            return "released"
        return await self.failed(sid, token, f"Original nicht lesbar ({exc.__class__.__name__})")

    # ---------------------------------------------------------------- results
    async def _finish(self, call, *args, **kw) -> None:
        try:
            await call(*args, **kw)
        except Exception as exc:  # the register takes the stage back after its timeout (PROJ-115)
            logger.warning("Could not report the result of %s to the register: %s", args[0], exc)

    async def release(self, sid: str, token: str, delay: float = 0) -> str:
        await self._finish(self.registry.release, sid, self.stage, token, int(delay))
        self.stats["released"] += 1
        return "released"

    async def failed(self, sid: str, token: str, error: str) -> str:
        logger.warning("%s of %s failed (retry by backoff): %s", self.name, sid, error)
        await self._finish(self.registry.fail, sid, self.stage, token, error[:1000], False)
        self.stats["failed"] += 1
        return "failed"

    async def failed_permanent(self, sid: str, token: str, error: str) -> str:
        logger.warning("%s of %s failed permanently: %s", self.name, sid, error)
        await self._finish(self.registry.fail, sid, self.stage, token, error[:1000], True)
        self.stats["failed_permanent"] += 1
        return "failed_permanent"

    async def done(self, sid: str, token: str, skipped: bool = False) -> str:
        await self._finish(self.registry.done, sid, self.stage, token, skipped)
        self.stats["skipped" if skipped else "done"] += 1
        return "skipped" if skipped else "done"

    async def write(self, sid: str, token: str, fields: dict, content: str | None = None) -> bool:
        """True if written; False if discarded (claim taken back, e.g. hand correction or deleted).
        RegistryUnavailable / RegistryConflict propagate (work goes back without a failed attempt)."""
        res = await self.registry.write(sid, self.stage, token=token, fields=fields, content=content,
                                        batch=self.s.batch)
        return not res.get("discarded")

    async def fix_title(self, sid: str, token: str) -> None:
        """After the own write: put the current place into the title if the image is described and the
        title is not protected (AK-29, AK-30)."""
        fm = (await self.registry.read_document(sid)).get("frontmatter") or {}
        manual = fm.get("manual") or []
        if "title" in manual or not fm.get("description_model") or not isinstance(fm.get("title"), str):
            return
        wanted = document.with_place(fm["title"], fm.get("location"))
        if wanted != fm["title"]:
            await self.write(sid, token, {"title": wanted})

    async def heartbeat(self, sid: str, token: str) -> None:
        while True:
            await asyncio.sleep(self.s.heartbeat_seconds)
            try:
                await self.registry.heartbeat(sid, self.stage, token)
            except RegistryConflict:
                logger.warning("Claim of %s lost (taken back by the register)", sid)
                return
            except Exception as exc:
                logger.warning("Heartbeat for %s failed: %s", sid, exc)

    async def run(self) -> None:
        while True:
            self.last_tick = time.monotonic()
            try:
                await self.step()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("%s: work loop step failed", self.name)
                await asyncio.sleep(self.s.poll_seconds)


class Describer(Base):
    name = "Beschreibung"
    stage = DESCRIBE

    def __init__(self, settings: Settings, registry: RegistryClient, store, vision: VisionClient):
        super().__init__(settings, registry, store)
        self.vision = vision
        self.cutoff: datetime | None = None
        self.active: dict[str, dict] = {}
        self.llm_paused_until = 0.0
        self.llm_reason = ""

    def health(self):
        errors, warnings = super().health()
        if self.llm_paused_until > time.monotonic():
            warnings.append(f"Vision-Modell nicht verfügbar, Beschreibung kurz pausiert: {self.llm_reason}")
        return errors, warnings

    async def boundary(self) -> datetime | None:
        """Time of the first start (backlog boundary), loaded once."""
        if self.cutoff is None:
            try:
                self.cutoff = await self.store.first_start()
                self._db_up()
                logger.info("Backlog = images registered before %s (released: %s)", self.cutoff.isoformat(),
                            self.s.backlog_released)
            except Exception as exc:
                self._db_down(exc)
        return self.cutoff

    def _reap(self) -> None:
        for sid in [s for s, a in self.active.items() if a["task"].done()]:
            self.active.pop(sid)

    async def wait_idle(self) -> None:
        tasks = [a["task"] for a in self.active.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._reap()

    async def stop(self) -> None:
        for a in self.active.values():
            a["task"].cancel()
        await self.wait_idle()

    async def claim(self, free: int) -> list[dict] | None:
        """Triggered images, then new ones, then the backlog if released. None: register paused/away."""
        cutoff = await self.boundary()
        if cutoff is None:
            return None
        items: list[dict] = []
        try:
            try:
                requested = await self.store.requested()
                self._db_up()
            except Exception as exc:
                self._db_down(exc)
                requested = []
            if requested:
                got = self._claimed(await self.registry.claim(self.stage, free, ids=requested))
                if got is None:
                    return None
                items += got
                try:
                    await self.store.forget(requested)
                except Exception as exc:
                    self._db_down(exc)
            if len(items) < free:
                got = self._claimed(await self.registry.claim(self.stage, free - len(items), since=cutoff))
                if got is None:
                    return items or None
                items += got
            if len(items) < free and self.s.backlog_released:
                got = self._claimed(await self.registry.claim(self.stage, free - len(items), before=cutoff))
                if got is None:
                    return items or None
                items += got
        except (RegistryUnavailable, RegistryError, RegistryNotFound) as exc:
            self._registry_down(exc)
            return items or None
        self._registry_up()
        return items

    async def step(self) -> int:
        self._reap()
        free = self.s.concurrency - len(self.active)
        if free <= 0:
            await asyncio.wait([a["task"] for a in self.active.values()], timeout=self.s.poll_seconds,
                               return_when=asyncio.FIRST_COMPLETED)
            return 0
        for until in (self.llm_paused_until, self.nas_paused_until):
            if until > time.monotonic():
                await asyncio.sleep(min(self.s.poll_seconds, until - time.monotonic()))
                return 0
        items = await self.claim(free)
        for item in items or []:
            entry = {"started": time.time(), "progress": "übernommen", "title": item.get("title")}
            entry["task"] = asyncio.create_task(self.process(item, entry))
            self.active[item["source_id"]] = entry
        if not items:
            await asyncio.sleep(self.s.poll_seconds)
        return len(items or [])

    async def process(self, item: dict, entry: dict | None = None) -> str:
        sid, token = item["source_id"], item["token"]
        entry = entry if entry is not None else {}
        hb = asyncio.create_task(self.heartbeat(sid, token))
        try:
            return await self._process(sid, token, entry)
        except Paused:
            return "released"
        finally:
            hb.cancel()

    async def _process(self, sid: str, token: str, entry: dict) -> str:
        src, path, paths = await self.original(sid, token)
        try:
            fm = (await self.registry.read_document(sid)).get("frontmatter") or {}
        except Exception as exc:  # repo away, markdown locked or missing: not the image's fault
            logger.warning("Markdown of %s cannot be read now: %s", sid, exc)
            return await self.release(sid, token)

        entry["progress"] = "Bild lesen"
        try:
            prep = await asyncio.to_thread(prepare, path, self.s.max_side_px, self.s.max_megapixels)
        except PermanentError as exc:
            return await self.failed_permanent(sid, token, str(exc))
        except OSError as exc:  # file system: NAS gone or file deleted in between
            return await self.os_error(sid, token, paths, exc)
        except Exception as exc:
            logger.exception("Unexpected error while reading image %s", sid)
            return await self.failed(sid, token, f"Unerwarteter Fehler: {exc.__class__.__name__}: {exc}"[:500])

        entry["progress"] = "Vision-Modell"

        def progress(text: str) -> None:
            entry["progress"] = text

        try:
            desc = await self.vision.describe(prep.jpegs, prep.landscape, fm.get("location"), progress)
        except VisionUnavailable as exc:
            self.llm_reason = str(exc)
            self.llm_paused_until = time.monotonic() + self.s.llm_retry_seconds
            return await self.failed(sid, token, str(exc))
        except TransientError as exc:
            return await self.failed(sid, token, str(exc))
        except Exception as exc:
            logger.exception("Unexpected error while describing %s", sid)
            return await self.failed(sid, token, f"Unerwarteter Fehler: {exc.__class__.__name__}: {exc}"[:500])
        self.llm_reason = ""

        info = prep.info
        prefix = document.time_prefix(info.taken, src.get("modified") or fm.get("modified"), self.s.timezone)
        title = document.with_place(document.base_title(prefix, desc.title), fm.get("location"))
        fields = {**info.fields(), "description_model": desc.model, "language": "de", "title": title}
        body = document.content(desc.description, desc.text, fm.get("locations") or [])
        entry["progress"] = "schreiben"
        try:
            if not await self.write(sid, token, fields, body):
                logger.info("Description of %s discarded (source changed or deleted meanwhile)", sid)
                self.stats["discarded"] += 1
                return await self.release(sid, token)
            await self.fix_title(sid, token)
        except (RegistryUnavailable, RegistryConflict) as exc:
            logger.warning("Writing the markdown of %s not possible now: %s", sid, exc)
            return await self.release(sid, token)
        except RegistryError as exc:
            return await self.failed(sid, token, f"Schreiben abgelehnt: {exc}"[:500])
        logger.info("Described %s (%d image(s), model %s)", sid, len(prep.jpegs), desc.model)
        return await self.done(sid, token)


def next_midnight(now: datetime, tz: str) -> datetime:
    local = now.astimezone(ZoneInfo(tz))
    nxt = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.replace(tzinfo=ZoneInfo(tz))


class Locator(Base):
    name = "Ort"
    stage = LOCATE

    def __init__(self, settings: Settings, registry: RegistryClient, store, weaviate: OldWeaviate | None,
                 geoapify: Geoapify, describer: Describer, clock=None):
        super().__init__(settings, registry, store)
        self.weaviate = weaviate if settings.location_takeover else None
        self.geoapify = geoapify
        self.describer = describer  # shares the backlog boundary
        self.clock = clock or (lambda: datetime.now(ZoneInfo(settings.timezone)))
        self.weaviate_paused_until = 0.0
        self.weaviate_reason = ""
        self.limit_day: date | None = None
        self.current: dict | None = None

    def health(self):
        errors, warnings = super().health()
        if self.weaviate_paused_until > time.monotonic():
            warnings.append(f"Altes Weaviate nicht erreichbar, Ort wartet: {self.weaviate_reason}")
        if self.limit_day is not None and self.limit_day == self.today():
            warnings.append("Geoapify-Tageslimit erreicht, Orte warten bis morgen")
        return errors, warnings

    def today(self) -> date:
        return self.clock().astimezone(ZoneInfo(self.s.timezone)).date()

    async def step(self) -> int:
        for until in (self.weaviate_paused_until, self.nas_paused_until):
            if until > time.monotonic():
                await asyncio.sleep(min(self.s.poll_seconds, until - time.monotonic()))
                return 0
        cutoff = await self.describer.boundary()
        items = None
        if cutoff is not None:
            try:
                items = self._claimed(await self.registry.claim(self.stage, 1, since=cutoff))
                if items == []:  # no new image open: the backlog (located regardless of the release, AK-31)
                    items = self._claimed(await self.registry.claim(self.stage, 1, before=cutoff))
                self._registry_up()
            except (RegistryUnavailable, RegistryError, RegistryNotFound) as exc:
                self._registry_down(exc)
                items = None
        if not items:
            await asyncio.sleep(self.s.poll_seconds)
            return 0
        item = items[0]
        self.current = {"source_id": item["source_id"], "title": item.get("title"), "started": time.time()}
        try:
            await self.process(item)
        finally:
            self.current = None
        return 1

    async def process(self, item: dict) -> str:
        sid, token = item["source_id"], item["token"]
        try:
            return await self._process(sid, token, item)
        except Paused:
            return "released"

    async def _process(self, sid: str, token: str, item: dict) -> str:
        src, path, paths = await self.original(sid, token)
        try:
            info = await asyncio.to_thread(read_exif, path)
        except PermanentError as exc:
            return await self.failed_permanent(sid, token, str(exc))
        except OSError as exc:
            return await self.os_error(sid, token, paths, exc)
        except Exception as exc:
            logger.exception("Unexpected error while reading EXIF of %s", sid)
            return await self.failed(sid, token, f"Unerwarteter Fehler: {exc.__class__.__name__}: {exc}"[:500])

        loc = None
        if info.gps:
            if self.weaviate is not None:
                try:
                    loc = await self.weaviate.lookup(src.get("hash") or item.get("hash") or "")
                    self.weaviate_reason = ""
                except WeaviateUnavailable as exc:  # no Geoapify, no failed attempt (AK-12)
                    self.weaviate_reason = str(exc)
                    if self.weaviate_paused_until <= time.monotonic():
                        logger.warning("Old Weaviate unavailable (%s); places wait %ss", exc,
                                       self.s.weaviate_retry_seconds)
                    self.weaviate_paused_until = time.monotonic() + self.s.weaviate_retry_seconds
                    return await self.release(sid, token, self.s.weaviate_retry_seconds)
            if loc is None:
                day = self.today()
                try:
                    reserved = await self.store.reserve_geocode(day, self.s.geoapify_daily_limit)
                    self._db_up()
                except Exception as exc:
                    self._db_down(exc)
                    return await self.release(sid, token, 60)
                if not reserved:  # daily limit: wait until tomorrow without a failed attempt (AK-14, EC-15)
                    if self.limit_day != day:
                        logger.info("Geoapify daily limit (%d) reached; places wait until tomorrow",
                                    self.s.geoapify_daily_limit)
                    self.limit_day = day
                    now = self.clock()
                    wait = (next_midnight(now, self.s.timezone) - now).total_seconds() + 5
                    return await self.release(sid, token, max(60, min(86400, wait)))
                try:
                    loc = await self.geoapify.reverse(info.gps["latitude"], info.gps["longitude"])
                except TransientError as exc:
                    return await self.failed(sid, token, str(exc))
        try:
            if not await self.write(sid, token, {"location": loc}):
                self.stats["discarded"] += 1
                return await self.release(sid, token)
            await self.fix_title(sid, token)
        except (RegistryUnavailable, RegistryConflict) as exc:
            logger.warning("Writing the place of %s not possible now: %s", sid, exc)
            return await self.release(sid, token)
        except RegistryError as exc:
            return await self.failed(sid, token, f"Schreiben abgelehnt: {exc}"[:500])
        if not info.gps:
            return await self.done(sid, token, skipped=True)  # no GPS: step skipped (AK-7)
        logger.info("Located %s", sid)
        return await self.done(sid, token)
