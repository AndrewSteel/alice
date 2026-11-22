"""Work loop of the extract stage: claim → find original → extract → write → done.

At most `concurrency` sources at the same time (AK-32). The markdown is written only after
the whole extraction succeeded, in one call (AK-34). While a source is in work, a heartbeat
keeps its claim alive in the register (AK-33).
"""
from __future__ import annotations

import asyncio
import logging
import os
import posixpath
import time

from .config import Settings
from .errors import PermanentError, TransientError
from .extractor import Extractor
from .registry import RegistryClient, RegistryConflict, RegistryError, RegistryUnavailable
from .text import Result, detect_language

logger = logging.getLogger("alice-text-extraction")

FOUND, MISSING, NAS_DOWN = "found", "missing", "nas_down"


def empty_content(path: str) -> str:
    return f"Kein Text extrahiert.\n\n- Original: [{posixpath.basename(path)}](<{path}>)"


class Worker:
    def __init__(self, settings: Settings, registry: RegistryClient, extractor: Extractor):
        self.s = settings
        self.registry = registry
        self.extractor = extractor
        self.active: dict[str, dict] = {}  # source id -> {"started", "progress", "task"}
        self.registry_down_since: float | None = None
        self.registry_reason = ""
        self.repo_paused_reason = ""
        self.nas_paused_until = 0.0
        self.nas_reason = ""
        self.last_tick = time.monotonic()
        self.stats = {"done": 0, "failed": 0, "failed_permanent": 0, "released": 0}

    # ---------------------------------------------------------------- health
    def health(self) -> tuple[list[str], list[str]]:
        errors, warnings = [], []
        if self.registry_down_since is not None:
            if time.monotonic() - self.registry_down_since >= self.s.registry_grace_seconds:
                errors.append(f"Extraktion pausiert: {self.registry_reason}")
            else:
                warnings.append(f"Extraktion pausiert: {self.registry_reason}")
        if time.monotonic() - self.last_tick > max(120.0, 3 * self.s.poll_seconds):
            errors.append("Arbeitsschleife läuft nicht")
        if self.repo_paused_reason:
            warnings.append(f"Register pausiert: {self.repo_paused_reason}")
        if self.nas_paused_until > time.monotonic():
            warnings.append(f"NAS nicht erreichbar, Extraktion pausiert: {self.nas_reason}")
        return errors, warnings

    def _registry_down(self, exc: Exception) -> None:
        if self.registry_down_since is None:
            self.registry_down_since = time.monotonic()
            logger.warning("Source register unavailable, extraction paused: %s", exc)
        self.registry_reason = str(exc)

    def _registry_up(self) -> None:
        if self.registry_down_since is not None:
            logger.info("Source register reachable again, extraction continues")
        self.registry_down_since = None
        self.registry_reason = ""

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

    def locate(self, paths: list[str]) -> tuple[str, str | None]:
        """First readable location (EC-8); otherwise NAS_DOWN if a share is missing, else MISSING."""
        for p in paths:
            if os.path.isfile(p) and os.access(p, os.R_OK):
                return FOUND, p
        if any(not self._share_reachable(p) for p in paths):
            return NAS_DOWN, None
        return MISSING, None

    # ---------------------------------------------------------------- loop
    async def run(self) -> None:
        while True:
            self.last_tick = time.monotonic()
            try:
                await self.step()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("work loop step failed")
                await asyncio.sleep(self.s.poll_seconds)

    async def step(self) -> int:
        """One round: wait for a free slot, claim work, start it. Returns the number of started sources."""
        self._reap()
        free = self.s.concurrency - len(self.active)
        if free <= 0:
            await asyncio.wait([a["task"] for a in self.active.values()], timeout=self.s.poll_seconds,
                               return_when=asyncio.FIRST_COMPLETED)
            return 0
        if self.nas_paused_until > time.monotonic():
            await asyncio.sleep(min(self.s.poll_seconds, self.nas_paused_until - time.monotonic()))
            return 0
        try:
            res = await self.registry.claim(free)
        except (RegistryUnavailable, RegistryError) as exc:
            self._registry_down(exc)
            await asyncio.sleep(self.s.poll_seconds)
            return 0
        self._registry_up()
        if res.get("paused"):
            if self.repo_paused_reason != res.get("reason"):
                logger.warning("Register paused (%s); waiting", res.get("reason"))
            self.repo_paused_reason = res.get("reason") or "pausiert"
            await asyncio.sleep(self.s.poll_seconds)
            return 0
        self.repo_paused_reason = ""
        items = res.get("items") or []
        for item in items:
            sid = item["source_id"]
            entry = {"started": time.time(), "progress": "übernommen", "title": item.get("title")}
            entry["task"] = asyncio.create_task(self.process(item, entry))
            self.active[sid] = entry
        if not items:
            await asyncio.sleep(self.s.poll_seconds)
        return len(items)

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

    # ---------------------------------------------------------------- one source
    async def _heartbeat(self, sid: str, token: str) -> None:
        while True:
            await asyncio.sleep(self.s.heartbeat_seconds)
            try:
                await self.registry.heartbeat(sid, token)
            except RegistryConflict:
                logger.warning("Claim of %s lost (taken back by the register)", sid)
                return
            except Exception as exc:
                logger.warning("Heartbeat for %s failed: %s", sid, exc)

    async def _finish(self, call, *args, **kw) -> None:
        try:
            await call(*args, **kw)
        except Exception as exc:  # the register takes the stage back after its timeout (PROJ-115)
            logger.warning("Could not report the result of %s to the register: %s", args[0], exc)

    async def process(self, item: dict, entry: dict | None = None) -> str:
        sid, token = item["source_id"], item["token"]
        entry = entry if entry is not None else {}
        hb = asyncio.create_task(self._heartbeat(sid, token))
        try:
            return await self._process(sid, token, entry)
        finally:
            hb.cancel()

    async def _process(self, sid: str, token: str, entry: dict) -> str:
        try:
            src = await self.registry.get_source(sid)
        except Exception as exc:
            logger.warning("Source %s could not be read from the register: %s", sid, exc)
            await self._finish(self.registry.release, sid, token)
            return "released"
        paths = [loc["path"] for loc in src.get("locations", []) if loc.get("present") and loc.get("path")]
        state, path = await asyncio.to_thread(self.locate, paths)
        if state == NAS_DOWN:
            return await self._nas_down(sid, token)
        if state == MISSING:
            # the file detection (PROJ-116) decides whether the source is gone; no failed attempt (AK-25)
            logger.info("Original of %s not found although the share is reachable; released", sid)
            await self._finish(self.registry.release, sid, token, self.s.missing_retry_seconds)
            self.stats["released"] += 1
            return "released"

        def progress(text: str) -> None:
            entry["progress"] = text

        try:
            result: Result = await asyncio.to_thread(self.extractor.extract, path, progress)
        except PermanentError as exc:
            logger.warning("Extraction of %s failed permanently: %s", sid, exc)
            await self._finish(self.registry.fail, sid, token, str(exc), True)
            self.stats["failed_permanent"] += 1
            return "failed_permanent"
        except (FileNotFoundError, OSError) as exc:
            state, _ = await asyncio.to_thread(self.locate, paths)
            if state == NAS_DOWN:
                return await self._nas_down(sid, token)
            if state == MISSING:  # deleted between claim and read (EC-9)
                await self._finish(self.registry.release, sid, token, self.s.missing_retry_seconds)
                self.stats["released"] += 1
                return "released"
            return await self._transient(sid, token, f"Original nicht lesbar ({exc.__class__.__name__})")
        except TransientError as exc:
            return await self._transient(sid, token, str(exc))
        except Exception as exc:
            logger.exception("Unexpected error while extracting %s", sid)
            return await self._transient(sid, token, f"Unerwarteter Fehler: {exc.__class__.__name__}: {exc}"[:500])

        content = result.markdown()
        language = None if result.empty else detect_language(content, self.s.language_min_chars)
        if result.empty:
            content = empty_content(path)
        fields = {"extraction": {"method": result.method, "ocr_pages": result.ocr_pages, "empty": result.empty},
                  "language": language}
        entry["progress"] = "schreiben"
        try:
            await self.registry.write(sid, fields=fields, content=content, batch=self.s.batch)
        except (RegistryUnavailable, RegistryConflict) as exc:
            # repo away or markdown locked by an invalid hand edit: not the document's fault
            logger.warning("Writing the markdown of %s not possible now: %s", sid, exc)
            await self._finish(self.registry.release, sid, token)
            self.stats["released"] += 1
            return "released"
        except RegistryError as exc:
            return await self._transient(sid, token, f"Schreiben abgelehnt: {exc}"[:500])
        await self._finish(self.registry.done, sid, token)
        self.stats["done"] += 1
        logger.info("Extracted %s (%s%s)", sid, result.method, ", empty" if result.empty else "")
        return "done"

    async def _transient(self, sid: str, token: str, error: str) -> str:
        logger.warning("Extraction of %s failed (retry by backoff): %s", sid, error)
        await self._finish(self.registry.fail, sid, token, error, False)
        self.stats["failed"] += 1
        return "failed"

    async def _nas_down(self, sid: str, token: str) -> str:
        self.nas_reason = "Freigabe des Originals fehlt"
        if self.nas_paused_until <= time.monotonic():
            logger.warning("NAS share of %s not reachable; work released, pausing for %ss", sid,
                           self.s.nas_retry_seconds)
        self.nas_paused_until = time.monotonic() + self.s.nas_retry_seconds
        await self._finish(self.registry.release, sid, token)
        self.stats["released"] += 1
        return "released"
