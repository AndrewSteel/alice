"""Own state in PostgreSQL (section 22 of init-schema.sql): first start (backlog boundary), Geoapify
calls per day, images triggered one by one."""
from __future__ import annotations

from datetime import date, datetime


class Store:
    def __init__(self, pool):
        self.pool = pool

    async def first_start(self) -> datetime:
        """Set once at the very first start: images registered before it are the backlog."""
        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO alice.image_processing_state (id) VALUES (1) ON CONFLICT DO NOTHING")
            return await con.fetchval("SELECT first_start FROM alice.image_processing_state WHERE id = 1")

    async def reserve_geocode(self, day: date, limit: int) -> bool:
        """Reserve one Geoapify call of `day` atomically; False if the daily limit is reached (AK-14)."""
        if limit <= 0:
            return False
        async with self.pool.acquire() as con:
            n = await con.fetchval(
                "INSERT INTO alice.image_geocode_usage (day, calls) VALUES ($1, 1) "
                "ON CONFLICT (day) DO UPDATE SET calls = alice.image_geocode_usage.calls + 1, updated_at = NOW() "
                "WHERE alice.image_geocode_usage.calls < $2 RETURNING calls", day, limit)
        return n is not None

    async def geocode_calls(self, day: date) -> int:
        async with self.pool.acquire() as con:
            return await con.fetchval("SELECT calls FROM alice.image_geocode_usage WHERE day = $1", day) or 0

    async def request(self, source_id: str) -> None:
        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO alice.image_describe_requests (source_id) VALUES ($1) "
                              "ON CONFLICT (source_id) DO UPDATE SET requested_at = NOW()", source_id)

    async def requested(self, limit: int = 100) -> list[str]:
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT source_id FROM alice.image_describe_requests "
                                   "ORDER BY requested_at, source_id LIMIT $1", limit)
        return [r["source_id"] for r in rows]

    async def forget(self, source_ids: list[str]) -> None:
        if source_ids:
            async with self.pool.acquire() as con:
                await con.execute("DELETE FROM alice.image_describe_requests WHERE source_id = ANY($1::text[])",
                                  source_ids)
