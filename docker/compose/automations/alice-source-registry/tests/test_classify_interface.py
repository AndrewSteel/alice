"""Interface extensions for the classification stage (PROJ-118): claim only after done prior stages,
reset per field, `manual` for single fields inside a block, write with claim token."""
from app import markdown as md

from .test_registry import claim_one, log, read_fm, register, stages


async def _extract_done(reg, sid, content="Rechnung Nr. 1\n\nBetrag 10,00 EUR"):
    tok = await claim_one(reg, "extract", sid)
    await reg.write_document(sid, stage="extract", fields={"language": "de"}, content=content)
    await reg.complete(sid, "extract", tok)


async def _classify_done(reg, sid, fields=None):
    tok = await claim_one(reg, "classify", sid)
    res = await reg.write_document(sid, stage="classify", token=tok, fields=fields or {
        "title": "2026-11-05 11.00.00 Rechnung", "type": "Invoice", "summary": "Eine Rechnung.",
        "fields": {"document_date": "2026-11-01", "amount_gross": 10.0, "iban": None}})
    await reg.complete(sid, "classify", tok)
    return res


async def test_claim_requires_done_stage(reg):  # AK-2
    sid = (await register(reg))["id"]
    assert (await reg.claim("classify", 10, ["document"], ["extract"]))["items"] == []
    tok = await claim_one(reg, "extract", sid)  # running
    assert (await reg.claim("classify", 10, ["document"], ["extract"]))["items"] == []
    await reg.fail(sid, "extract", tok, "kaputt")  # failed
    assert (await reg.claim("classify", 10, ["document"], ["extract"]))["items"] == []
    await reg.retry(sid, "extract")
    await _extract_done(reg, sid)
    items = (await reg.claim("classify", 10, ["document"], ["extract"]))["items"]
    assert [i["source_id"] for i in items] == [sid]


async def test_stage_reset_rules_listed(reg):
    st = {s["name"]: s for s in await reg.list_stages()}
    assert st["classify"]["resets_on_fields"] == ["content", "type"]
    assert st["database"]["resets_on_fields"] == []


async def test_new_content_from_extract_resets_classify(reg):  # AK-37 (first half), spec "Erneute Klassifizierung" 1
    sid = (await register(reg))["id"]
    await _extract_done(reg, sid)
    await _classify_done(reg, sid)
    # extract runs again (e.g. "erneut versuchen") with the same content → classify stays done
    await reg.retry(sid, "extract")
    await _extract_done(reg, sid)
    assert (await stages(reg, sid))["classify"]["state"] == "done"
    # ... with a different content → classify pending
    await reg.retry(sid, "extract")
    await _extract_done(reg, sid, content="Rechnung Nr. 1\n\nBetrag 12,00 EUR")
    st = await stages(reg, sid)
    assert st["classify"]["state"] == "pending"
    assert st["database"]["state"] == "pending"


async def test_hand_edit_of_type_and_content_resets_classify(reg, repo_dir):  # AK-34, AK-35
    sid = (await register(reg))["id"]
    await _extract_done(reg, sid)
    await _classify_done(reg, sid)
    path = (await reg.get_source(sid))["path"]
    text = (repo_dir / path).read_text()
    (repo_dir / path).write_text(text.replace("type: Invoice", "type: Contract"))
    await reg.scan()
    fm, _ = read_fm(repo_dir, path)
    assert "type" in fm["manual"]
    assert (await stages(reg, sid))["classify"]["state"] == "pending"
    await _classify_done(reg, sid, {"title": "2026-11-05 11.00.00 Rechnung", "type": "Invoice"})
    fm, _ = read_fm(repo_dir, (await reg.get_source(sid))["path"])
    assert fm["type"] == "Contract"  # hand type wins
    # content corrected by hand
    path = (await reg.get_source(sid))["path"]
    text = (repo_dir / path).read_text()
    (repo_dir / path).write_text(text.replace("10,00", "100,00"))
    await reg.scan()
    assert (await stages(reg, sid))["classify"]["state"] == "pending"


async def test_hand_edit_of_single_fields_keeps_classify(reg, repo_dir):  # AK-36
    sid = (await register(reg))["id"]
    await _extract_done(reg, sid)
    await _classify_done(reg, sid)
    path = (await reg.get_source(sid))["path"]
    text = (repo_dir / path).read_text()
    text = text.replace("amount_gross: 10.0", "amount_gross: 11.5").replace("Eine Rechnung.", "Meine Rechnung.")
    text = text.replace("title: 2026-11-05 11.00.00 Rechnung", "title: Stromrechnung von Hand")
    (repo_dir / path).write_text(text)
    await reg.scan()
    src = await reg.get_source(sid)
    fm, _ = read_fm(repo_dir, src["path"])
    assert sorted(fm["manual"]) == ["fields.amount_gross", "summary", "title"]
    st = src["stages"]
    assert st["classify"]["state"] == "done"
    assert st["database"]["state"] == "pending" and st["rag"]["state"] == "pending"
    assert st["wiki"]["state"] == "pending"


async def test_manual_inner_field_survives_rewrite(reg, repo_dir):  # AK-38, AK-15
    sid = (await register(reg))["id"]
    await _extract_done(reg, sid)
    await _classify_done(reg, sid)
    path = (await reg.get_source(sid))["path"]
    text = (repo_dir / path).read_text().replace("iban: null", "iban: DE89370400440532013000")
    (repo_dir / path).write_text(text)
    await reg.scan()
    await reg.retry(sid, "classify")
    await _classify_done(reg, sid, {"title": "2026-11-05 11.00.00 Vertrag", "type": "Contract",
                                    "fields": {"document_date": "2026-11-02", "contract_type": "Strom"}})
    fm, _ = read_fm(repo_dir, (await reg.get_source(sid))["path"])
    assert fm["fields"] == {"document_date": "2026-11-02", "contract_type": "Strom",
                            "iban": "DE89370400440532013000"}  # invoice field gone, manual field kept
    assert fm["type"] == "Contract"


async def test_write_with_stale_token_is_discarded(reg, repo_dir):  # EC-9, EC-15
    sid = (await register(reg))["id"]
    await _extract_done(reg, sid)
    tok = await claim_one(reg, "classify", sid)
    path = (await reg.get_source(sid))["path"]
    before = (repo_dir / path).read_text()
    # hand correction of the content while classify runs: committed first, classify result discarded
    (repo_dir / path).write_text(before.replace("10,00", "20,00"))
    res = await reg.write_document(sid, stage="classify", token=tok, fields={"type": "Invoice"})
    assert res["discarded"] is True
    fm, content = read_fm(repo_dir, path)
    assert fm["type"] is None and "20,00" in content
    assert log(repo_dir, path)[0].startswith("Alice Hand-Korrektur|manual:")
    assert (await stages(reg, sid))["classify"]["state"] == "pending"


async def test_write_for_deleted_source_is_discarded(reg, repo_dir):  # EC-15
    sid = (await register(reg))["id"]
    await _extract_done(reg, sid)
    tok = await claim_one(reg, "classify", sid)
    await reg.remove_location(sid, {"path": "/nas/scanner/scan_0042.pdf"})
    path = (await reg.get_source(sid))["path"]
    before = (repo_dir / path).read_text()
    res = await reg.write_document(sid, stage="classify", token=tok, fields={"type": "Invoice"})
    assert res["discarded"] is True
    assert (repo_dir / path).read_text() == before


async def test_changed_parts_and_keep_manual_parts():
    assert md.changed_parts("fields", {"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}) == ["fields.b", "fields.c"]
    assert md.changed_parts("title", "x", "y") == ["title"]
    assert md.changed_parts("fields", None, {"a": 1}) == ["fields"]
    assert md.keep_manual_parts("fields", {"a": 9, "b": 9}, {"a": 1}, ["fields.a", "fields.b"]) == {"a": 1, "b": 9}
    assert md.keep_manual_parts("title", "t", "old", ["title.x"]) == "t"
