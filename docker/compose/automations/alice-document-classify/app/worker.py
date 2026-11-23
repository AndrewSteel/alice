"""Work loop of the classify stage: claim → read markdown → LLM steps → one write → done.

At most `concurrency` sources at the same time (AK-41). The frontmatter is written only after all
LLM steps of a source succeeded (AK-45). While a source is in work, a heartbeat keeps its claim alive
(the gateway queue can be long while chat and voice have priority).
"""
from __future__ import annotations

import asyncio
import logging
import time

from .classifier import Classifier, PermanentError
from .config import Settings
from .llm import InvalidAnswer, LlmError, LlmUnavailable
from .registry import RegistryClient, RegistryConflict, RegistryError, RegistryUnavailable

logger = logging.getLogger("alice-document-classify")


class Worker:
    def __init__(self, settings: Settings, registry: RegistryClient, classifier: Classifier):
        self.s = settings
        self.registry = registry
        self.classifier = classifier
        self.active: dict[str, dict] = {}  # source id -> {"started", "progress", "task"}
        self.registry_down_since: float | None = None
        self.registry_reason = ""
        self.repo_paused_reason = ""
        self.llm_paused_until = 0.0
        self.llm_reason = ""
        self.llm_key_rejected = False
        self.last_tick = time.monotonic()
        self.stats = {"done": 0, "failed": 0, "failed_permanent": 0, "released": 0, "discarded": 0}

    # ---------------------------------------------------------------- health
    def health(self) -> tuple[list[str], list[str]]:
        errors, warnings = [], []
        if self.registry_down_since is not None:
            if time.monotonic() - self.registry_down_since >= self.s.registry_grace_seconds:
                errors.append(f"Klassifizierung pausiert: {self.registry_reason}")
            else:
                warnings.append(f"Klassifizierung pausiert: {self.registry_reason}")
        if time.monotonic() - self.last_tick > max(120.0, 3 * self.s.poll_seconds):
            errors.append("Arbeitsschleife läuft nicht")
        if self.repo_paused_reason:
            warnings.append(f"Register pausiert: {self.repo_paused_reason}")
        if self.llm_paused_until > time.monotonic():
            (errors if self.llm_key_rejected else warnings).append(
                f"LLM nicht verfügbar, Klassifizierung pausiert: {self.llm_reason}")
        return errors, warnings

    def _registry_down(self, exc: Exception) -> None:
        if self.registry_down_since is None:
            self.registry_down_since = time.monotonic()
            logger.warning("Source register unavailable, classification paused: %s", exc)
        self.registry_reason = str(exc)

    def _registry_up(self) -> None:
        if self.registry_down_since is not None:
            logger.info("Source register reachable again, classification continues")
        self.registry_down_since = None
        self.registry_reason = ""

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
        if self.llm_paused_until > time.monotonic():
            await asyncio.sleep(min(self.s.poll_seconds, self.llm_paused_until - time.monotonic()))
            return 0
        if self.llm_reason:
            logger.info("Trying the LLM gateway again")
            self.llm_reason, self.llm_key_rejected = "", False
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

    async def _release(self, sid: str, token: str) -> str:
        await self._finish(self.registry.release, sid, token)
        self.stats["released"] += 1
        return "released"

    async def _process(self, sid: str, token: str, entry: dict) -> str:
        try:
            doc = await self.registry.read_document(sid)
        except Exception as exc:  # repo away, markdown locked or missing: not the document's fault
            logger.warning("Markdown of %s cannot be read now: %s", sid, exc)
            return await self._release(sid, token)

        def progress(text: str) -> None:
            entry["progress"] = text

        try:
            fields = await self.classifier.run(doc["frontmatter"], doc["content"], progress)
        except LlmUnavailable as exc:
            self.llm_reason, self.llm_key_rejected = str(exc), exc.key_rejected
            if self.llm_paused_until <= time.monotonic():
                logger.warning("LLM gateway unavailable (%s); work released, pausing for %ss", exc,
                               self.s.llm_retry_seconds)
            self.llm_paused_until = time.monotonic() + self.s.llm_retry_seconds
            return await self._release(sid, token)
        except PermanentError as exc:
            logger.warning("Classification of %s failed permanently: %s", sid, exc)
            await self._finish(self.registry.fail, sid, token, str(exc), True)
            self.stats["failed_permanent"] += 1
            return "failed_permanent"
        except (InvalidAnswer, LlmError) as exc:
            return await self._failed(sid, token, str(exc))
        except Exception as exc:
            logger.exception("Unexpected error while classifying %s", sid)
            return await self._failed(sid, token, f"Unerwarteter Fehler: {exc.__class__.__name__}: {exc}"[:500])

        entry["progress"] = "schreiben"
        try:
            res = await self.registry.write(sid, fields=fields, token=token, batch=self.s.batch)
        except (RegistryUnavailable, RegistryConflict) as exc:
            logger.warning("Writing the markdown of %s not possible now: %s", sid, exc)
            return await self._release(sid, token)
        except RegistryError as exc:
            return await self._failed(sid, token, f"Schreiben abgelehnt: {exc}"[:500])
        if res.get("discarded"):
            # hand correction or deletion meanwhile (EC-9, EC-15): the register took the work back
            logger.info("Result for %s discarded (source changed or deleted during classification)", sid)
            await self._finish(self.registry.release, sid, token)
            self.stats["discarded"] += 1
            return "discarded"
        await self._finish(self.registry.done, sid, token)
        self.stats["done"] += 1
        logger.info("Classified %s as %s", sid, fields.get("type", "(hand type)"))
        return "done"

    async def _failed(self, sid: str, token: str, error: str) -> str:
        logger.warning("Classification of %s failed (retry by backoff): %s", sid, error)
        await self._finish(self.registry.fail, sid, token, error, False)
        self.stats["failed"] += 1
        return "failed"
