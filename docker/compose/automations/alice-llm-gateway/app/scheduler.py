"""Priority slot scheduler (PROJ-111).

llama-3090 has exactly one processing slot. The scheduler hands that slot to
at most one request at a time: the oldest waiting INTERACTIVE request first,
the oldest BACKGROUND request only when no interactive one is waiting. Within a
tier requests are served in arrival order. The queue lives in memory only.
"""
from __future__ import annotations

import asyncio
from collections import deque

INTERACTIVE = "interactive"
BACKGROUND = "background"
TIERS = (INTERACTIVE, BACKGROUND)  # priority order


class SlotScheduler:
    def __init__(self) -> None:
        self._queues: dict[str, deque[asyncio.Future]] = {t: deque() for t in TIERS}
        self._busy = False

    def queue_length(self, tier: str) -> int:
        return len(self._queues[tier])

    @property
    def busy(self) -> bool:
        return self._busy

    async def acquire(self, tier: str) -> None:
        """Wait until the slot is ours. Cancelling the caller drops the request
        from the queue (or hands the slot on if it was granted concurrently)."""
        if not self._busy:
            self._busy = True
            return
        fut = asyncio.get_running_loop().create_future()
        queue = self._queues[tier]
        queue.append(fut)
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                # Slot was granted in the same tick the caller went away.
                self.release()
            else:
                try:
                    queue.remove(fut)
                except ValueError:
                    pass
            raise

    def release(self) -> None:
        """Free the slot and grant it to the next waiting request, if any."""
        for tier in TIERS:
            queue = self._queues[tier]
            while queue:
                fut = queue.popleft()
                if not fut.done():
                    fut.set_result(None)  # slot stays busy, ownership moves on
                    return
        self._busy = False
