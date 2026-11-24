"""Work loop of the database stage: claim → read frontmatter → convert → replace rows → done.

At most `concurrency` documents at the same time. A source is never worked on twice at the same time
inside this process (it can be handed out again while still in work when the register took the claim
back, e.g. on deletion, EC-5); the second run waits for the first and then sees the current state.
"""
from __future__ import annotations

import asyncio
import logging
import time

from .config import Settings
from .convert import InvalidValue, convert
from .registry import RegistryClient, RegistryConflict, RegistryError, RegistryUnavailable
from .store import UNAVAILABLE, Store

logger = logging.getLogger("alice-document-database")


class Worker:
    def __init__(self, settings: Settings, registry: RegistryClient, store: Store):
        self.s = settings
        self.registry = registry
        self.store = store
        self.active: dict[str, dict] = {}  # claim token -> {"source_id", "started", "progress", "task"}
        self.locks: dict[str, dict] = {}  # source id -> {"lock", "users"}
        self.registry_down_since: float | None = None
        self.registry_reason = ""
        self.repo_paused_reason = ""
        self.db_paused_until = 0.0
        self.db_reason = ""
        self.last_tick = time.monotonic()
        self.stats = {"written": 0, "removed": 0, "failed": 0, "released": 0}

    # ---------------------------------------------------------------- health
    def health(self) -> tuple[list[str], list[str]]:
        errors, warnings = [], []
        if self.registry_down_since is not None:
            if time.monotonic() - self.registry_down_since >= self.s.registry_grace_seconds:
                errors.append(f"DB-Stufe pausiert: {self.registry_reason}")
            else:
                warnings.append(f"DB-Stufe pausiert: {self.registry_reason}")
        if time.monotonic() - self.last_tick > max(120.0, 3 * self.s.poll_seconds):
            errors.append("Arbeitsschleife läuft nicht")
        if self.repo_paused_reason:
            warnings.append(f"Register pausiert: {self.repo_paused_reason}")
        if self.db_reason:
            warnings.append(f"PostgreSQL nicht erreichbar, DB-Stufe pausiert: {self.db_reason}")
        return errors, warnings

    def _registry_down(self, exc: Exception) -> None:
        if self.registry_down_since is None:
            self.registry_down_since = time.monotonic()
            logger.warning("Source register unavailable, database stage paused: %s", exc)
        self.registry_reason = str(exc)

    def _registry_up(self) -> None:
        if self.registry_down_since is not None:
            logger.info("Source register reachable again, database stage continues")
        self.registry_down_since = None
        self.registry_reason = ""

    def _db_down(self, exc: BaseException) -> None:
        reason = f"{exc.__class__.__name__}: {exc}"[:300]
        if not self.db_reason:
            logger.warning("PostgreSQL unavailable (%s); work released, pausing for %ss", reason,
                           self.s.db_retry_seconds)
        self.db_reason = reason
        self.db_paused_until = time.monotonic() + self.s.db_retry_seconds

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
        if self.db_paused_until > time.monotonic():
            await asyncio.sleep(min(self.s.poll_seconds, self.db_paused_until - time.monotonic()))
            return 0
        if self.db_reason:  # pause over: is PostgreSQL back? (AK-30)
            try:
                await self.store.ping()
            except UNAVAILABLE as exc:
                self._db_down(exc)
                return 0
            logger.info("PostgreSQL reachable again, database stage continues")
            self.db_reason = ""
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
            entry = {"source_id": item["source_id"], "started": time.time(), "progress": "übernommen",
                     "title": item.get("title")}
            entry["task"] = asyncio.create_task(self.process(item, entry))
            self.active[item["token"]] = entry
        if not items:
            await asyncio.sleep(self.s.poll_seconds)
        return len(items)

    def _reap(self) -> None:
        for token in [t for t, a in self.active.items() if a["task"].done()]:
            self.active.pop(token)

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
                logger.info("Claim of %s taken back by the register (changed or deleted meanwhile)", sid)
                return
            except Exception as exc:
                logger.warning("Heartbeat for %s failed: %s", sid, exc)

    async def _finish(self, call, *args, **kw) -> None:
        try:
            await call(*args, **kw)
        except RegistryConflict:
            # the register took the claim back meanwhile (hand correction, deletion): the stage is
            # pending again and the next run writes the current state
            logger.info("Result of %s not reported: claim taken back by the register", args[0])
        except Exception as exc:  # the register takes the stage back after its timeout (PROJ-115)
            logger.warning("Could not report the result of %s to the register: %s", args[0], exc)

    async def process(self, item: dict, entry: dict | None = None) -> str:
        sid, token = item["source_id"], item["token"]
        entry = entry if entry is not None else {}
        slot = self.locks.setdefault(sid, {"lock": asyncio.Lock(), "users": 0})
        slot["users"] += 1
        hb = asyncio.create_task(self._heartbeat(sid, token))
        try:
            async with slot["lock"]:
                return await self._process(item, sid, token, entry)
        finally:
            hb.cancel()
            slot["users"] -= 1
            if not slot["users"]:
                self.locks.pop(sid, None)

    async def _release(self, sid: str, token: str) -> str:
        await self._finish(self.registry.release, sid, token)
        self.stats["released"] += 1
        return "released"

    async def _process(self, item: dict, sid: str, token: str, entry: dict) -> str:
        if item.get("deleted"):
            entry["progress"] = "entfernen"
            try:
                removed = await self.store.remove(sid)
            except UNAVAILABLE as exc:
                self._db_down(exc)
                return await self._release(sid, token)
            except Exception as exc:
                logger.exception("Removing %s failed", sid)
                return await self._failed(sid, token, f"Entfernen fehlgeschlagen: {exc.__class__.__name__}: {exc}")
            await self._finish(self.registry.done, sid, token)
            if removed:
                self.stats["removed"] += 1
                logger.info("Removed deleted source %s from the document tables", sid)
            return "removed"

        entry["progress"] = "lesen"
        try:
            doc = await self.registry.read_document(sid)
        except Exception as exc:  # repo away, markdown locked or missing: not the document's fault (AK-29)
            logger.warning("Markdown of %s cannot be read now: %s", sid, exc)
            return await self._release(sid, token)

        try:
            rows = convert(sid, doc["path"], doc["frontmatter"])
        except InvalidValue as exc:  # AK-27: the DB keeps the last valid state
            return await self._failed(sid, token, str(exc))

        entry["progress"] = "schreiben"
        try:
            await self.store.replace(rows)
        except UNAVAILABLE as exc:  # AK-30: no failed attempt
            self._db_down(exc)
            return await self._release(sid, token)
        except Exception as exc:
            logger.exception("Writing %s failed", sid)
            return await self._failed(sid, token, f"Schreiben in die Datenbank fehlgeschlagen: "
                                                  f"{exc.__class__.__name__}: {exc}")
        await self._finish(self.registry.done, sid, token)
        self.stats["written"] += 1
        logger.info("Wrote %s (%s, %d bookings, %d line items)", sid, rows.type, len(rows.transactions),
                    len(rows.line_items))
        return "done"

    async def _failed(self, sid: str, token: str, error: str) -> str:
        error = error[:2000]
        logger.warning("Database stage of %s failed (retry by backoff): %s", sid, error)
        await self._finish(self.registry.fail, sid, token, error)
        self.stats["failed"] += 1
        return "failed"
