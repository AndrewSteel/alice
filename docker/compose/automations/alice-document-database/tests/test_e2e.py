"""End to end against the real register (in-process), the throwaway PostgreSQL and a temporary git repo.
Skipped without TEST_POSTGRES_DSN (scripts/test-services.sh sets it)."""
import asyncio
import json
import logging
from datetime import date
from decimal import Decimal

from .conftest import IBAN_A, IBAN_B, ISIN, git, later

INVOICE = {"document_date": "2026-10-14", "sender": "Stadtwerke Musterstadt", "recipient": "Familie Muster",
           "tags": ["strom", "rechnung"], "invoice_number": "R-2026-10", "invoice_date": "2026-10-14",
           "due_date": "2026-10-28", "amount_gross": 119.0, "amount_net": 100.0, "vat_rate": 19.0,
           "currency": "EUR", "line_items": [
               {"description": "Arbeitspreis", "quantity": 250.5, "amount": 75.15},
               {"description": "Grundpreis", "quantity": 1.0, "amount": 12.5},
               {"description": "Zähler", "quantity": None, "amount": 31.35}]}
CONTRACT = {"document_date": "2026-01-02", "sender": "Stadtwerke Musterstadt", "recipient": None, "tags": None,
            "contract_type": "Stromvertrag", "contract_partner": "Stadtwerke Musterstadt", "sign_date": "2026-01-02",
            "start_date": "2026-02-01", "end_date": None, "notice_period": "3 Monate", "monthly_cost": 30.0,
            "annual_cost": 360.0, "currency": "EUR"}
SECURITY = {"document_date": "2026-09-01", "sender": "Musterbank", "recipient": None, "tags": ["depot"],
            "bank": "Musterbank", "depot_number": "DEP-0001", "transaction_date": "2026-09-01",
            "security_name": "Muster Welt ETF", "isin": ISIN, "transaction_type": "buy", "quantity": 0.000123,
            "price": 1250000.0, "settlement_amount": 153.75, "currency": "EUR"}


def tx(day, amount, purpose="Miete", counterparty="Vermieter", value_date=None):
    return {"booking_date": f"2026-10-{day:02d}", "value_date": value_date, "counterparty": counterparty,
            "purpose": purpose, "amount": amount}


def statement(transactions, iban=IBAN_A, **extra):
    return {"document_date": "2026-10-31", "sender": "Musterbank", "recipient": None, "tags": None,
            "bank_name": "Musterbank", "account_holder": "Familie Muster", "iban": iban,
            "period_from": "2026-10-01", "period_to": "2026-10-31", "opening_balance": 1000.0,
            "closing_balance": 1000.0 + sum(t["amount"] for t in transactions if t["amount"] is not None),
            "currency": "EUR", "transactions": transactions, **extra}


async def bookings(env, sid):
    return await env.fetch("SELECT * FROM alice.doc_bank_transactions WHERE document_id = $1 ORDER BY position", sid)


async def marks(env, sid):
    """position -> (document id, position) of the original, or None."""
    rows = await env.fetch(
        "SELECT t.position, o.document_id, o.position AS opos FROM alice.doc_bank_transactions t "
        "LEFT JOIN alice.doc_bank_transactions o ON o.id = t.duplicate_of WHERE t.document_id = $1 "
        "ORDER BY t.position", sid)
    return {r["position"]: (r["document_id"], r["opos"]) if r["document_id"] else None for r in rows}


# ---------------------------------------------------------------- flow
async def test_document_flow_and_no_repo_change(env):  # AK-1, AK-6, AK-7
    sid = await env.add("Document", {"document_date": "2026-10-01", "sender": "Amt", "recipient": "Familie Muster",
                                     "tags": ["behörde", "brief"]}, uncertain=True, lang_uncertain=True)
    assert (await env.stage(sid))["state"] == "pending"
    head, status = git(env.repo, "rev-parse", "HEAD"), git(env.repo, "status", "--porcelain")
    path = (await env.reg.get_source(sid))["path"]
    text = (env.repo / path).read_text()
    await env.run()
    assert (await env.stage(sid))["state"] == "done"
    assert git(env.repo, "rev-parse", "HEAD") == head and git(env.repo, "status", "--porcelain") == status
    assert (env.repo / path).read_text() == text
    row = await env.fetchrow("SELECT * FROM alice.doc_documents WHERE id = $1", sid)
    assert row["type"] == "Document" and row["title"] == "Testdokument" and row["summary"] == "Eine Zusammenfassung."
    assert row["tags"] == ["behörde", "brief"] and row["document_date"] == date(2026, 10, 1)
    assert row["sender"] == "Amt" and row["recipient"] == "Familie Muster" and row["language"] == "de"
    assert row["classification_confidence"] == Decimal("0.9") and row["classification_uncertain"] is True
    assert row["summary_language_uncertain"] is True  # AK-12
    assert row["modified"] is not None and row["captured"] is not None
    assert row["markdown_path"] == path and json.loads(row["locations"]) == [{"path": "/mnt/nas/share/1-scan.pdf"}]
    for table in ("doc_invoices", "doc_bank_statements", "doc_security_settlements", "doc_contracts"):
        assert await env.fetchval(f"SELECT count(*) FROM alice.{table}") == 0


async def test_only_classified_documents(env):  # AK-2, AK-3
    waiting = await env.register()  # classify pending
    extracted = await env.register()
    await env.extract(extracted)
    failed = await env.register()
    await env.extract(failed)
    tok = await env._claim("classify", failed)
    await env.reg.fail(failed, "classify", tok, "kaputt", True)  # failed_permanent
    running = await env.register()
    await env.extract(running)
    await env._claim("classify", running)  # running
    image = await env.register(kind="image")
    await env.extract(image, kind="image")  # classify and database are skipped for images (PROJ-125)
    await env.run()
    for sid in (waiting, extracted, failed, running, image):
        assert (await env.stage(sid))["state"] in ("pending", "skipped"), sid
    assert await env.fetchval("SELECT count(*) FROM alice.doc_documents") == 0


async def test_backlog_on_first_start(env):  # AK-5
    ids = [await env.add("Invoice", INVOICE) for _ in range(5)]
    await env.run()
    assert await env.fetchval("SELECT count(*) FROM alice.doc_invoices") == 5
    assert all([(await env.stage(s))["state"] == "done" for s in ids])


# ---------------------------------------------------------------- mapping
async def test_all_types_with_all_fields(env):  # AK-8, AK-9, AK-11, EC-7
    inv = await env.add("Invoice", INVOICE)
    con = await env.add("Contract", CONTRACT)
    sec = await env.add("SecuritySettlement", SECURITY)
    bank = await env.add("BankStatement", statement([tx(1, -500.0), tx(2, 2500.0, "Gehalt", "Arbeitgeber")]))
    await env.run()
    assert {r["type"] for r in await env.fetch("SELECT type FROM alice.doc_documents")} == {
        "Invoice", "Contract", "SecuritySettlement", "BankStatement"}
    i = await env.fetchrow("SELECT * FROM alice.doc_invoices WHERE document_id = $1", inv)
    assert (i["invoice_number"], i["invoice_date"], i["due_date"]) == ("R-2026-10", date(2026, 10, 14), date(2026, 10, 28))
    assert (i["amount_gross"], i["amount_net"], i["vat_rate"], i["currency"]) == (
        Decimal("119.0"), Decimal("100.0"), Decimal("19.0"), "EUR")
    items = await env.fetch("SELECT * FROM alice.doc_invoice_line_items WHERE document_id = $1 ORDER BY position", inv)
    assert [(r["position"], r["description"], r["quantity"], r["amount"]) for r in items] == [
        (1, "Arbeitspreis", Decimal("250.5"), Decimal("75.15")), (2, "Grundpreis", Decimal("1.0"), Decimal("12.5")),
        (3, "Zähler", None, Decimal("31.35"))]
    c = await env.fetchrow("SELECT * FROM alice.doc_contracts WHERE document_id = $1", con)
    assert (c["contract_type"], c["contract_partner"], c["sign_date"], c["start_date"], c["end_date"]) == (
        "Stromvertrag", "Stadtwerke Musterstadt", date(2026, 1, 2), date(2026, 2, 1), None)
    assert (c["notice_period"], c["monthly_cost"], c["annual_cost"], c["currency"]) == (
        "3 Monate", Decimal("30.0"), Decimal("360.0"), "EUR")
    assert (await env.fetchrow("SELECT recipient, tags FROM alice.doc_documents WHERE id = $1", con)) == (None, None)
    s = await env.fetchrow("SELECT * FROM alice.doc_security_settlements WHERE document_id = $1", sec)
    assert (s["bank"], s["depot_number"], s["transaction_date"], s["security_name"], s["isin"]) == (
        "Musterbank", "DEP-0001", date(2026, 9, 1), "Muster Welt ETF", ISIN)
    assert (s["transaction_type"], s["quantity"], s["price"], s["settlement_amount"], s["currency"]) == (
        "buy", Decimal("0.000123"), Decimal("1250000.0"), Decimal("153.75"), "EUR")
    b = await env.fetchrow("SELECT * FROM alice.doc_bank_statements WHERE document_id = $1", bank)
    assert (b["bank_name"], b["account_holder"], b["iban"], b["period_from"], b["period_to"]) == (
        "Musterbank", "Familie Muster", IBAN_A, date(2026, 10, 1), date(2026, 10, 31))
    assert (b["opening_balance"], b["closing_balance"], b["currency"]) == (Decimal("1000.0"), Decimal("3000.0"), "EUR")
    assert b["balance_mismatch"] is None and b["balance_difference"] is None
    rows = await bookings(env, bank)
    assert [(r["position"], r["booking_date"], r["value_date"], r["counterparty"], r["purpose"], r["amount"],
             r["currency"]) for r in rows] == [
        (1, date(2026, 10, 1), None, "Vermieter", "Miete", Decimal("-500.0"), "EUR"),
        (2, date(2026, 10, 2), None, "Arbeitgeber", "Gehalt", Decimal("2500.0"), "EUR")]


async def test_250_bookings_sum_exact(env):  # AK-10
    txs = [tx(1 + i % 28, round((-1) ** i * (i * 1.37 + 0.01), 2), f"Zweck {i}", value_date=f"2026-10-{1 + i % 28:02d}")
           for i in range(250)]
    sid = await env.add("BankStatement", statement(txs))
    await env.run()
    rows = await bookings(env, sid)
    assert len(rows) == 250 and [r["position"] for r in rows] == list(range(1, 251))
    assert [r["purpose"] for r in rows] == [f"Zweck {i}" for i in range(250)]
    fm_txs = (await env.frontmatter(sid))["fields"]["transactions"]
    expected = sum(Decimal(repr(t["amount"])) for t in fm_txs)
    assert await env.fetchval("SELECT sum(amount) FROM alice.doc_bank_transactions WHERE document_id = $1", sid) == expected


async def test_flags_and_empty_statement(env):  # AK-12, AK-13
    flagged = await env.add("BankStatement", statement([tx(1, 10.0)], balance_mismatch=True, balance_difference=50.0))
    empty = await env.add("BankStatement", statement([]))
    await env.run()
    assert await env.fetchrow("SELECT balance_mismatch, balance_difference FROM alice.doc_bank_statements "
                              "WHERE document_id = $1", flagged) == (True, Decimal("50.0"))
    assert await env.fetchval("SELECT count(*) FROM alice.doc_bank_statements WHERE document_id = $1", empty) == 1
    assert await bookings(env, empty) == []


async def test_several_thousand_bookings(env):  # EC-6
    sid = await env.add("BankStatement", statement([tx(1 + i % 28, 1.5, f"Z{i}") for i in range(3000)]))
    await env.run()
    assert await env.fetchval("SELECT count(*) FROM alice.doc_bank_transactions WHERE document_id = $1", sid) == 3000


# ---------------------------------------------------------------- changes and hand corrections
async def test_hand_correction_lands_in_db(env):  # AK-14, AK-4
    sid = await env.add("Invoice", INVOICE)
    await env.run()
    await env.hand_edit(sid, lambda fm: fm["fields"].update(amount_gross=130.5))
    assert "fields.amount_gross" in (await env.frontmatter(sid))["manual"]
    assert (await env.stage(sid))["state"] == "pending"
    await env.run()
    assert await env.fetchval("SELECT amount_gross FROM alice.doc_invoices WHERE document_id = $1", sid) == Decimal("130.5")


async def test_new_version_replaces_bookings(env):  # AK-15
    txs = [tx(i + 1, float(i + 1), f"Zweck {i}") for i in range(10)]
    sid = await env.add("BankStatement", statement(txs))
    await env.run()
    assert len(await bookings(env, sid)) == 10

    def nine(fm):
        t = fm["fields"]["transactions"]
        del t[3]
        t[0]["amount"] = 99.99
    await env.hand_edit(sid, nine)
    await env.run()
    rows = await bookings(env, sid)
    assert len(rows) == 9 and rows[0]["amount"] == Decimal("99.99")
    assert [r["purpose"] for r in rows] == [f"Zweck {i}" for i in range(10) if i != 3]


async def test_type_change(env):  # AK-16
    sid = await env.add("Invoice", INVOICE)
    await env.run()
    assert await env.fetchval("SELECT count(*) FROM alice.doc_invoice_line_items WHERE document_id = $1", sid) == 3
    # new classification (e.g. after a content change) as a contract
    await env.reg.retry(sid, "classify")
    await env.classify(sid, "Contract", CONTRACT)
    await env.run()
    assert await env.fetchval("SELECT type FROM alice.doc_documents WHERE id = $1", sid) == "Contract"
    assert await env.fetchval("SELECT count(*) FROM alice.doc_invoices WHERE document_id = $1", sid) == 0
    assert await env.fetchval("SELECT count(*) FROM alice.doc_invoice_line_items WHERE document_id = $1", sid) == 0
    assert await env.fetchval("SELECT contract_partner FROM alice.doc_contracts WHERE document_id = $1", sid) == \
        "Stadtwerke Musterstadt"


async def test_manual_value_survives_rebuild(env):  # AK-17 (rebuild simulated: all stages again, PROJ-115)
    sid = await env.add("Invoice", INVOICE)
    await env.run()
    await env.hand_edit(sid, lambda fm: fm["fields"].update(amount_gross=222.22))
    await env.run()
    for stage in ("extract", "classify", "database"):
        await env.reg.retry(sid, stage)
    await env.extract(sid)
    await env.classify(sid, "Invoice", INVOICE)  # the LLM would write 119.0 again
    await env.run()
    assert (await env.frontmatter(sid))["fields"]["amount_gross"] == 222.22
    assert await env.fetchval("SELECT amount_gross FROM alice.doc_invoices WHERE document_id = $1", sid) == Decimal("222.22")
    assert (await env.stage(sid))["state"] == "done"


async def test_direct_db_change_is_overwritten(env):  # AK-18
    sid = await env.add("Invoice", INVOICE)
    await env.run()
    async with env.pool.acquire() as con:
        await con.execute("UPDATE alice.doc_invoices SET amount_gross = 1 WHERE document_id = $1", sid)
        await con.execute("DELETE FROM alice.doc_invoice_line_items WHERE document_id = $1 AND position = 2", sid)
    await env.reg.retry(sid, "database")
    await env.run()
    assert await env.fetchval("SELECT amount_gross FROM alice.doc_invoices WHERE document_id = $1", sid) == Decimal("119.0")
    assert await env.fetchval("SELECT count(*) FROM alice.doc_invoice_line_items WHERE document_id = $1", sid) == 3


async def test_abort_in_the_middle_keeps_old_state(env):  # AK-19
    sid = await env.add("BankStatement", statement([tx(i + 1, 1.0) for i in range(10)]))
    await env.run()
    await env.hand_edit(sid, lambda fm: fm["fields"]["transactions"].extend([tx(20, 2.0), tx(21, 3.0)]))
    items = (await env.client.claim(5))["items"]
    assert [i["source_id"] for i in items] == [sid]
    doc = await env.client.read_document(sid)
    from app.convert import convert

    class Killed(BaseException):
        pass

    async def kill():
        # all new rows are written inside the transaction, then the process "dies"
        assert await env.fetchval("SELECT count(*) FROM alice.doc_bank_transactions WHERE document_id = $1", sid) == 10
        raise Killed()
    try:
        await env.store.replace(convert(sid, doc["path"], doc["frontmatter"]), before_commit=kill)
    except Killed:
        pass
    assert len(await bookings(env, sid)) == 10  # complete old state
    assert (await env.stage(sid))["state"] == "running"
    # register timeout (PROJ-115): the stage is handed out again and finished
    async with env.pool.acquire() as con:
        await con.execute("UPDATE alice.source_stages SET started_at = NOW() - interval '2 hours' "
                          "WHERE source_id = $1 AND stage = 'database'", sid)
    assert await env.reg.reset_stale() == 1
    await env.run()
    assert len(await bookings(env, sid)) == 12 and (await env.stage(sid))["state"] == "done"


# ---------------------------------------------------------------- deletion
async def test_deleted_source_removed_and_back(env):  # AK-20, AK-21
    bank = await env.add("BankStatement", statement([tx(1, 1.0), tx(2, 2.0)]))
    inv = await env.add("Invoice", INVOICE)
    await env.run()
    path = (await env.reg.get_source(inv))["locations"][0]["path"]
    await env.delete(bank)
    await env.delete(inv)
    assert (await env.stage(bank))["state"] == "pending"
    await env.run()
    for table, col in (("doc_documents", "id"), ("doc_bank_statements", "document_id"),
                       ("doc_bank_transactions", "document_id"), ("doc_invoices", "document_id"),
                       ("doc_invoice_line_items", "document_id")):
        assert await env.fetchval(f"SELECT count(*) FROM alice.{table} WHERE {col} = ANY($1::text[])",
                                  [bank, inv]) == 0, table
    assert (await env.stage(inv))["state"] == "done"
    # the original shows up again (same hash)
    await env.reg.add_location(inv, {"path": path})
    await env.run()
    assert await env.fetchval("SELECT count(*) FROM alice.doc_invoice_line_items WHERE document_id = $1", inv) == 3
    assert json.loads(await env.fetchval("SELECT locations FROM alice.doc_documents WHERE id = $1", inv)) == \
        [{"path": path}]


async def test_location_change_updates_locations(env):  # locations stay current
    sid = await env.add("Document", {})
    await env.run()
    await env.reg.add_location(sid, {"path": "/mnt/nas/other/copy.pdf"})
    await env.run()
    locs = json.loads(await env.fetchval("SELECT locations FROM alice.doc_documents WHERE id = $1", sid))
    assert {"path": "/mnt/nas/other/copy.pdf"} in locs and len(locs) == 2


async def test_deleted_during_processing(env):  # EC-5
    sid = await env.add("Invoice", INVOICE)
    items = (await env.client.claim(5))["items"]
    doc = await env.client.read_document(sid)
    await env.delete(sid)  # the register takes the claim back
    from app.convert import convert
    await env.store.replace(convert(sid, doc["path"], doc["frontmatter"]))  # old run still writes
    await env.worker._finish(env.client.done, sid, items[0]["token"])  # conflict: only logged
    await env.run()
    assert await env.fetchval("SELECT count(*) FROM alice.doc_documents WHERE id = $1", sid) == 0
    assert (await env.stage(sid))["state"] == "done"


# ---------------------------------------------------------------- duplicates
async def test_duplicate_marked_in_later_statement(env):  # AK-22
    a = await env.add("BankStatement", statement([tx(1, -500.0), tx(5, -20.0, "Strom")]), captured=later(0))
    b = await env.add("BankStatement", statement([tx(5, -20.0, "Strom"), tx(7, -9.0, "Kino")]), captured=later(60))
    await env.run()
    assert await marks(env, a) == {1: None, 2: None}
    assert await marks(env, b) == {1: (a, 2), 2: None}
    total = await env.fetchval("SELECT sum(amount) FROM alice.doc_bank_transactions WHERE duplicate_of IS NULL")
    assert total == Decimal("-529.0")


async def test_duplicate_independent_of_order(env):  # AK-23
    b = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(60))
    await env.run()
    assert await marks(env, b) == {1: None}
    a = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(0))
    await env.run()
    assert await marks(env, a) == {1: None} and await marks(env, b) == {1: (a, 1)}


async def test_original_deleted_unmarks(env):  # AK-24
    a = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(0))
    b = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(60))
    await env.run()
    await env.delete(a)
    await env.run()
    assert await marks(env, b) == {1: None}


async def test_no_marks_same_statement_other_iban_no_iban(env):  # AK-25
    same = await env.add("BankStatement", statement([tx(5, -20.0), tx(5, -20.0)]), captured=later(0))
    other = await env.add("BankStatement", statement([tx(5, -20.0)], iban=IBAN_B), captured=later(10))
    none1 = await env.add("BankStatement", statement([tx(6, -1.0)], iban=None), captured=later(20))
    none2 = await env.add("BankStatement", statement([tx(6, -1.0)], iban=None), captured=later(30))
    await env.run()
    for sid in (same, other, none1, none2):
        assert all(v is None for v in (await marks(env, sid)).values()), sid


async def test_changed_original_unmarks(env):  # AK-26
    a = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(0))
    b = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(60))
    await env.run()
    assert await marks(env, b) == {1: (a, 1)}
    await env.hand_edit(a, lambda fm: fm["fields"]["transactions"][0].update(amount=-21.0))
    await env.run()
    assert await marks(env, b) == {1: None}


async def test_three_statements_and_original_deleted(env):  # EC-1, EC-2
    a = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(0))
    b = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(10))
    c = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(20))
    await env.run()
    assert await marks(env, b) == {1: (a, 1)} and await marks(env, c) == {1: (a, 1)}
    await env.delete(a)
    await env.run()
    assert await marks(env, b) == {1: None} and await marks(env, c) == {1: (b, 1)}


async def test_iban_changed_by_hand(env):  # EC-3
    a = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(0))
    b = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")]), captured=later(10))
    c = await env.add("BankStatement", statement([tx(5, -20.0, "Strom")], iban=IBAN_B), captured=later(20))
    await env.run()
    assert await marks(env, b) == {1: (a, 1)} and await marks(env, c) == {1: None}
    await env.hand_edit(b, lambda fm: fm["fields"].update(iban=IBAN_B))
    await env.run()
    assert await marks(env, b) == {1: None} and await marks(env, c) == {1: (b, 1)}


async def test_parallel_statements_same_account(env):  # EC-4
    ids = [await env.add("BankStatement", statement([tx(5, -20.0, "Strom"), tx(6, -1.0, None)]), captured=later(i))
           for i in range(4)]
    env.worker.s.concurrency = 4
    await env.run()
    assert await marks(env, ids[0]) == {1: None, 2: None}
    for sid in ids[1:]:
        assert await marks(env, sid) == {1: (ids[0], 1), 2: (ids[0], 2)}  # EC-8: both without purpose


async def test_missing_date_or_amount_not_compared(env):  # EC-8
    a = await env.add("BankStatement", statement([{"booking_date": None, "amount": -1.0, "purpose": "x"},
                                                  {"booking_date": "2026-10-01", "amount": None, "purpose": "x"}]),
                      captured=later(0))
    b = await env.add("BankStatement", statement([{"booking_date": None, "amount": -1.0, "purpose": "x"},
                                                  {"booking_date": "2026-10-01", "amount": None, "purpose": "x"}]),
                      captured=later(10))
    await env.run()
    assert await marks(env, a) == {1: None, 2: None} and await marks(env, b) == {1: None, 2: None}


# ---------------------------------------------------------------- errors
async def _fail_until_permanent(env, sid):
    for attempt in range(2, 6):  # the first attempt failed already
        async with env.pool.acquire() as con:  # backoff over
            await con.execute("UPDATE alice.source_stages SET next_retry_at = NOW() "
                              "WHERE source_id = $1 AND stage = 'database' AND state = 'failed'", sid)
        await env.run()
        st = await env.stage(sid)
        assert st["attempts"] == attempt
    return st


async def test_invalid_hand_correction(env):  # AK-27, AK-28
    sid = await env.add("Invoice", INVOICE)
    await env.run()
    await env.hand_edit(sid, lambda fm: fm["fields"].update(amount_gross="zwölf"))
    await env.run()
    st = await env.stage(sid)
    assert st["state"] == "failed" and "fields.amount_gross" in st["last_error"] and "zwölf" in st["last_error"]
    assert await env.fetchval("SELECT amount_gross FROM alice.doc_invoices WHERE document_id = $1", sid) == Decimal("119.0")
    st = await _fail_until_permanent(env, sid)
    assert st["state"] == "failed_permanent"
    # the human corrects the value → database runs again
    await env.hand_edit(sid, lambda fm: fm["fields"].update(amount_gross=12.0))
    await env.run()
    assert (await env.stage(sid))["state"] == "done"
    assert await env.fetchval("SELECT amount_gross FROM alice.doc_invoices WHERE document_id = $1", sid) == Decimal("12.0")


async def test_invalid_date_and_transactions_text(env):  # AK-27
    inv = await env.add("Invoice", INVOICE)
    bank = await env.add("BankStatement", statement([tx(1, 1.0)]))
    await env.run()
    await env.hand_edit_text(inv, "invoice_date: '2026-10-14'", "invoice_date: 31.13.2026")
    await env.hand_edit(bank, lambda fm: fm["fields"].update(transactions="eine Buchung"))
    await env.run()
    st = await env.stage(inv)
    assert st["state"] == "failed" and "fields.invoice_date" in st["last_error"] and "31.13.2026" in st["last_error"]
    st = await env.stage(bank)
    assert st["state"] == "failed" and "fields.transactions" in st["last_error"] and "eine Buchung" in st["last_error"]
    assert await env.fetchval("SELECT invoice_date FROM alice.doc_invoices WHERE document_id = $1", inv) == date(2026, 10, 14)
    assert len(await bookings(env, bank)) == 1


async def test_locked_markdown_keeps_db(env):  # AK-29
    sid = await env.add("Invoice", INVOICE)
    await env.run()
    path = env.repo / (await env.reg.get_source(sid))["path"]
    path.write_text(path.read_text().replace("amount_gross: 119.0", "amount_gross: [unclosed"))
    await env.reg.scan()
    assert (await env.reg.get_source(sid))["repo_error"]
    await env.reg.retry(sid, "database")
    await env.run()
    assert (await env.stage(sid))["state"] == "pending"  # not handed out while locked
    assert await env.fetchval("SELECT amount_gross FROM alice.doc_invoices WHERE document_id = $1", sid) == Decimal("119.0")


async def test_postgres_unavailable_releases_without_attempt(env, caplog):  # AK-30
    from app.store import Store

    sid = await env.add("Invoice", INVOICE)
    good = env.worker.store
    env.worker.store = Store("postgresql://alice:test@127.0.0.1:1/alice")  # nothing listens there
    with caplog.at_level(logging.WARNING, logger="alice-document-database"):
        await env.worker.step()
        await env.worker.wait_idle()
    st = await env.stage(sid)
    assert st["state"] == "pending" and st["attempts"] == 0
    assert any("PostgreSQL unavailable" in r.message for r in caplog.records)
    errors, warnings = env.worker.health()
    assert not errors and any("PostgreSQL nicht erreichbar" in w for w in warnings)
    await env.worker.store.close()
    env.worker.store = good  # PostgreSQL back
    await asyncio.sleep(0.06)
    await env.run()
    assert (await env.stage(sid))["state"] == "done" and env.worker.health() == ([], [])
    assert await env.fetchval("SELECT count(*) FROM alice.doc_invoices WHERE document_id = $1", sid) == 1


async def test_classify_pending_again_keeps_db(env):  # EC-10
    sid = await env.add("Invoice", INVOICE)
    await env.run()
    await env.reg.retry(sid, "classify")
    await env.reg.retry(sid, "database")
    await env.run()
    assert (await env.stage(sid))["state"] == "pending"
    assert await env.fetchval("SELECT count(*) FROM alice.doc_invoices WHERE document_id = $1", sid) == 1
