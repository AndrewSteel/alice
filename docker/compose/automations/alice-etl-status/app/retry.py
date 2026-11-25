"""
"Retry" of failed stages (PROJ-122 AK-13–19). The register route also accepts pending/done;
the view only allows failed/failed_permanent of sources that are neither locked nor deleted,
so the check lives here. Every retry is logged as an event at the source with the admin's name.
"""
from __future__ import annotations

import asyncio
import logging

from . import queries
from .upstream import Client, Rejected

logger = logging.getLogger("alice-etl-status.retry")

STATE_DE = {"pending": "wartend", "running": "läuft", "done": "erledigt", "failed": "fehlgeschlagen",
            "failed_permanent": "endgültig fehlgeschlagen", "skipped": "übersprungen"}


class NotRetryable(Exception):
    def __init__(self, reason: str, detail: str, state: str | None = None):
        super().__init__(detail)
        self.reason = reason
        self.state = state


class LimitExceeded(Exception):
    def __init__(self, count: int, limit: int):
        super().__init__(f"Auswahl mit {count} Quellen über der Grenze von {limit}: bitte einen Neuaufbau nutzen")
        self.count = count
        self.limit = limit


class SourceNotFound(Exception):
    pass


async def _retry_stage(registry: Client, source_id: str, stage: str, admin: str, before: str, attempts: int) -> dict:
    res = await registry.call("POST", f"/sources/{source_id}/stages/{stage}/retry")
    await registry.call("POST", f"/sources/{source_id}/events", json={
        "level": "info", "event": "manual_retry",
        "message": f"Stufe {stage} erneut versucht von {admin} (vorher {before}, {attempts} Versuche)"})
    return res


async def retry_one(pool, registry: Client, source_id: str, stage: str, admin: str) -> dict:
    async with pool.acquire() as con:
        row = await queries.stage_state(con, source_id, stage)
    if row is None:
        raise SourceNotFound(f"Quelle {source_id} unbekannt")
    if row["state"] is None:
        raise SourceNotFound(f"Stufe {stage} der Quelle {source_id} unbekannt")
    if row["deleted"]:
        raise NotRetryable("deleted", "Quelle ist gelöscht: kein erneuter Versuch", row["state"])
    if row["repo_error"] is not None:
        raise NotRetryable("locked", "Quelle ist gesperrt (ungültiges Frontmatter): Quell-Markdown von Hand "
                                     "reparieren", row["state"])
    if row["state"] not in queries.RETRYABLE:
        raise NotRetryable("state", f"Stufe {stage} ist {STATE_DE.get(row['state'], row['state'])}: "
                                    "kein erneuter Versuch nötig", row["state"])
    res = await _retry_stage(registry, source_id, stage, admin, row["state"], row["attempts"])
    logger.info("Retry %s/%s by %s", source_id, stage, admin)
    return {"id": source_id, "stage": stage, "state": res.get("state", "pending"), "attempts": res.get("attempts", 0)}


async def retry_bulk(pool, registry: Client, targets_fn, limit: int, admin: str, dry_run: bool,
                     parallel: int = 10) -> dict:
    """targets_fn(con) → {source: [stages]} of the selection, evaluated now (EC-2). More sources than the
    limit → LimitExceeded, nothing changed (AK-18)."""
    async with pool.acquire() as con:
        targets = await targets_fn(con)
    n = len(targets)
    if dry_run:
        return {"sources": n, "limit": limit, "allowed": n <= limit}
    if n > limit:
        raise LimitExceeded(n, limit)
    sem = asyncio.Semaphore(parallel)
    done = {"sources": 0, "stages": 0, "skipped": 0}

    async def one(sid: str, stages: list[str]):
        async with sem:
            hit = False
            for st in stages:
                try:
                    await retry_one(pool, registry, sid, st, admin)
                    done["stages"] += 1
                    hit = True
                except (NotRetryable, SourceNotFound, Rejected):  # changed meanwhile: leave it as it is
                    done["skipped"] += 1
            if hit:
                done["sources"] += 1

    await asyncio.gather(*(one(sid, st) for sid, st in targets.items()))
    logger.info("Bulk retry by %s: %d sources, %d stages, %d skipped", admin, done["sources"], done["stages"],
                done["skipped"])
    return {**done, "limit": limit}
