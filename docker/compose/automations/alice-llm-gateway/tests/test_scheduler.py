import asyncio

import pytest

from app.scheduler import BACKGROUND, INTERACTIVE, SlotScheduler


async def _tick():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_free_slot_is_granted_immediately():
    s = SlotScheduler()
    await asyncio.wait_for(s.acquire(BACKGROUND), 0.1)
    assert s.busy
    s.release()
    assert not s.busy


async def test_interactive_overtakes_20_waiting_background():
    s = SlotScheduler()
    await s.acquire(BACKGROUND)  # running background request holds the slot
    served: list[str] = []

    async def req(name, tier):
        await s.acquire(tier)
        served.append(name)

    tasks = [asyncio.create_task(req(f"bg{i}", BACKGROUND)) for i in range(20)]
    await _tick()
    tasks.append(asyncio.create_task(req("chat", INTERACTIVE)))
    await _tick()
    assert s.queue_length(BACKGROUND) == 20 and s.queue_length(INTERACTIVE) == 1

    for _ in range(21):
        s.release()
        await _tick()
    assert served[0] == "chat"
    assert served[1:] == [f"bg{i}" for i in range(20)]
    await asyncio.gather(*tasks)


async def test_fifo_within_tier_and_interactive_first():
    s = SlotScheduler()
    await s.acquire(INTERACTIVE)
    served: list[str] = []

    async def req(name, tier):
        await s.acquire(tier)
        served.append(name)

    order = [("b1", BACKGROUND), ("i1", INTERACTIVE), ("b2", BACKGROUND), ("i2", INTERACTIVE)]
    tasks = []
    for name, tier in order:
        tasks.append(asyncio.create_task(req(name, tier)))
        await _tick()
    for _ in order:
        s.release()
        await _tick()
    assert served == ["i1", "i2", "b1", "b2"]
    s.release()
    assert not s.busy
    await asyncio.gather(*tasks)


async def test_cancelled_waiter_is_dropped_and_never_granted():
    s = SlotScheduler()
    await s.acquire(BACKGROUND)
    waiter = asyncio.create_task(s.acquire(INTERACTIVE))
    await _tick()
    assert s.queue_length(INTERACTIVE) == 1
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert s.queue_length(INTERACTIVE) == 0
    s.release()
    assert not s.busy  # nobody left to hand the slot to


async def test_cancel_after_grant_hands_slot_on():
    s = SlotScheduler()
    await s.acquire(BACKGROUND)
    first = asyncio.create_task(s.acquire(INTERACTIVE))
    second = asyncio.create_task(s.acquire(BACKGROUND))
    await _tick()
    s.release()          # grants `first` ...
    first.cancel()       # ... which is cancelled before it resumes
    with pytest.raises(asyncio.CancelledError):
        await first
    await asyncio.wait_for(second, 0.1)  # slot moved on instead of leaking
    assert s.busy
    s.release()
    assert not s.busy
