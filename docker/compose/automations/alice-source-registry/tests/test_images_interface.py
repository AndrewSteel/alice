"""Interface extensions for images (PROJ-125): stages of images, claim by registration time and by id,
done as skipped, in-place change resets a skipped `locate`."""
import asyncio
from datetime import datetime, timezone

from .test_registry import claim_one, register, stages


async def image(reg, n: int, **kw):
    return (await register(reg, h=f"sha256:{n:064x}", title=f"IMG_{n}.jpg", path=f"/nas/fotos/IMG_{n}.jpg",
                           kind="image", **kw))["id"]


async def test_image_stages(reg):  # PROJ-125 AK-5
    img = await image(reg, 1)
    doc = (await register(reg, h="sha256:" + "d" * 64))["id"]
    st = await stages(reg, img)
    assert st["classify"]["state"] == "skipped" and st["database"]["state"] == "skipped"
    assert st["extract"]["state"] == "pending" and st["locate"]["state"] == "pending"
    assert (await stages(reg, doc))["locate"]["state"] == "skipped"
    assert (await stages(reg, doc))["classify"]["state"] == "pending"


async def test_claim_by_registration_time(reg, pool):  # PROJ-125 AK-31, AK-32
    old = await image(reg, 1)
    await asyncio.sleep(0.05)
    cut = datetime.now(timezone.utc)
    await asyncio.sleep(0.05)
    new = await image(reg, 2)
    got = (await reg.claim("extract", 10, ["image"], registered_since=cut))["items"]
    assert [i["source_id"] for i in got] == [new]
    got = (await reg.claim("extract", 10, ["image"], registered_before=cut))["items"]
    assert [i["source_id"] for i in got] == [old]


async def test_claim_by_ids(reg):  # PROJ-125 AK-33
    a, b = await image(reg, 1), await image(reg, 2)
    got = (await reg.claim("extract", 10, ["image"], source_ids=[b]))["items"]
    assert [i["source_id"] for i in got] == [b]
    assert (await stages(reg, a))["extract"]["state"] == "pending"


async def test_claim_never_hands_out_deleted_or_other_kinds(reg):  # PROJ-125 AK-4, AK-6
    img = await image(reg, 1)
    gone = await image(reg, 2)
    await register(reg, h="sha256:" + "d" * 64)
    await reg.remove_location(gone, {"path": "/nas/fotos/IMG_2.jpg"})
    got = (await reg.claim("extract", 10, ["image"]))["items"]
    assert [i["source_id"] for i in got] == [img]


async def test_done_skipped_and_reset_on_new_original(reg):  # PROJ-125 AK-7, AK-36
    img = await image(reg, 1)
    tok = await claim_one(reg, "locate", img)
    assert (await reg.complete(img, "locate", tok, skipped=True))["state"] == "skipped"
    tok = await claim_one(reg, "extract", img)
    await reg.complete(img, "extract", tok)
    # original changed in place: description and place run again; classify/database stay skipped
    res = await reg.update_original(img, hash="sha256:" + "f" * 64, size=1, modified=None)
    assert {"extract", "locate"} <= set(res["reset"])
    st = await stages(reg, img)
    assert st["locate"]["state"] == "pending" and st["extract"]["state"] == "pending"
    assert st["classify"]["state"] == "skipped" and st["database"]["state"] == "skipped"
