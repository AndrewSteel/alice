"""Interface extensions for the extraction stage (PROJ-117): permanent failure, heartbeat,
claim by kind, release with delay."""
import pytest

from app.service import Conflict

from .test_registry import claim_one, register, stages


async def test_permanent_fail_at_once(reg):  # PROJ-117 AK-21, AK-22
    sid = (await register(reg))["id"]
    tok = await claim_one(reg, "extract", sid)
    row = await reg.fail(sid, "extract", tok, "PDF ist passwortgeschützt", permanent=True)
    assert row["state"] == "failed_permanent" and row["attempts"] == 1 and row["next_retry_at"] is None
    assert row["last_error"] == "PDF ist passwortgeschützt"
    assert not [i for i in (await reg.claim("extract", 10))["items"] if i["source_id"] == sid]
    # "retry" makes it claimable again (AK-27)
    assert (await reg.retry(sid, "extract"))["state"] == "pending"
    assert await claim_one(reg, "extract", sid)


async def test_normal_fail_unchanged(reg):
    sid = (await register(reg))["id"]
    tok = await claim_one(reg, "extract", sid)
    row = await reg.fail(sid, "extract", tok, "Zeitüberschreitung")
    assert row["state"] == "failed" and row["next_retry_at"] is not None


async def test_heartbeat_keeps_stage_running(make_registry, pool):  # PROJ-117 AK-33
    reg = await make_registry(stale_running_seconds=60)
    sid = (await register(reg))["id"]
    tok = await claim_one(reg, "extract", sid)
    async with pool.acquire() as con:
        await con.execute("UPDATE alice.source_stages SET started_at = NOW() - interval '50 s' "
                          "WHERE source_id = $1 AND stage = 'extract'", sid)
    await reg.heartbeat(sid, "extract", tok)
    async with pool.acquire() as con:
        await con.execute("UPDATE alice.source_stages SET started_at = started_at - interval '30 s' "
                          "WHERE source_id = $1 AND stage = 'extract'", sid)
    # 80 s since the claim, but only 30 s since the heartbeat → still running
    assert await reg.reset_stale() == 0
    assert (await stages(reg, sid))["extract"]["state"] == "running"
    await reg.complete(sid, "extract", tok)
    with pytest.raises(Conflict):  # no heartbeat for work that is no longer claimed
        await reg.heartbeat(sid, "extract", tok)


async def test_claim_by_kind(reg):  # PROJ-117 AK-3
    img = (await register(reg, h="sha256:" + "1" * 16, title="foto.jpg", path="/nas/foto.jpg", kind="image"))["id"]
    doc = (await register(reg, h="sha256:" + "2" * 16))["id"]
    items = (await reg.claim("extract", 10, ["document"]))["items"]
    assert [i["source_id"] for i in items] == [doc]
    assert (await stages(reg, img))["extract"]["state"] == "pending"
    # the image is still handed out to a claim without kind filter (other stages/workers)
    assert img in [i["source_id"] for i in (await reg.claim("extract", 10))["items"]]


async def test_release_with_delay(reg, pool):  # PROJ-117 AK-25
    sid = (await register(reg))["id"]
    tok = await claim_one(reg, "extract", sid)
    row = await reg.release(sid, "extract", tok, delay_seconds=3600)
    assert row["state"] == "pending" and row["attempts"] == 0
    assert not [i for i in (await reg.claim("extract", 10))["items"] if i["source_id"] == sid]
    assert not [i for i in (await reg.claim("extract", 10, ["document"]))["items"] if i["source_id"] == sid]
    async with pool.acquire() as con:
        await con.execute("UPDATE alice.source_stages SET next_retry_at = NOW() - interval '1 s' "
                          "WHERE source_id = $1 AND stage = 'extract'", sid)
    tok = await claim_one(reg, "extract", sid)
    row = await reg.release(sid, "extract", tok)  # without delay: due at once, as before
    assert row["next_retry_at"] is None
    assert await claim_one(reg, "extract", sid)
