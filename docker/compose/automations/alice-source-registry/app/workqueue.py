"""Work queue in Redis: one sorted set per stage (member = source id, score = due time).

Redis is only a queue: PostgreSQL holds the truth and the queue is rebuilt from it
whenever the ready marker is missing (e.g. Redis restarted without persistence).
Every Redis error is logged and swallowed; callers fall back to the register.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("alice-source-registry.queue")

PREFIX = "sot:queue:"
READY_KEY = "sot:queue:ready"
KEY_TTL = 86400
READY_TTL = 3600
CHUNK = 1000


def key(stage: str) -> str:
    return f"{PREFIX}{stage}"


class WorkQueue:
    def __init__(self, client):
        self.client = client

    async def push(self, stage: str, items: dict[str, float]) -> None:
        if not self.client or not items:
            return
        try:
            await self.client.zadd(key(stage), items)
            await self.client.expire(key(stage), KEY_TTL)
        except Exception as exc:
            logger.warning("queue push failed (%s); register stays authoritative", exc)

    async def remove(self, stage: str, source_id: str) -> None:
        if not self.client:
            return
        try:
            await self.client.zrem(key(stage), source_id)
        except Exception as exc:
            logger.warning("queue remove failed: %s", exc)

    async def due(self, stage: str, limit: int) -> list[str] | None:
        """Due source ids, or None when Redis is not usable (caller uses the register)."""
        if not self.client:
            return None
        try:
            if not await self.client.exists(READY_KEY):
                return None
            items = await self.client.zrangebyscore(key(stage), "-inf", time.time(), start=0, num=limit)
            return [i.decode() if isinstance(i, bytes) else i for i in items]
        except Exception as exc:
            logger.warning("queue read failed (%s); using register", exc)
            return None

    async def is_ready(self) -> bool:
        if not self.client:
            return True
        try:
            return bool(await self.client.exists(READY_KEY))
        except Exception:
            return False

    async def rebuild(self, stages: list[str], rows) -> bool:
        """Replace the queue with (stage, source_id, due_ts) rows from the register."""
        if not self.client:
            return False
        try:
            by_stage: dict[str, dict[str, float]] = {s: {} for s in stages}
            for stage, source_id, due in rows:
                by_stage.setdefault(stage, {})[source_id] = due
            for stage, items in by_stage.items():
                await self.client.delete(key(stage))
                pairs = list(items.items())
                for i in range(0, len(pairs), CHUNK):
                    await self.client.zadd(key(stage), dict(pairs[i:i + CHUNK]))
                if pairs:
                    await self.client.expire(key(stage), KEY_TTL)
            await self.client.set(READY_KEY, "1", ex=READY_TTL)
            return True
        except Exception as exc:
            logger.warning("queue rebuild failed: %s", exc)
            return False
