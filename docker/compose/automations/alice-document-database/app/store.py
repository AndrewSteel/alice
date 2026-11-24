"""Writes the rows of one document into alice.doc_* — always the complete state in one transaction
(AK-14–19) — and determines the duplicate marks of the bookings of the affected accounts (AK-22–26).
"""
from __future__ import annotations

import asyncio
import json

import asyncpg

from .convert import DETAIL, DETAIL_TABLE, LINE_ITEM, TRANSACTION, Document

# Errors that mean "PostgreSQL not reachable right now" (AK-30): no failed attempt.
UNAVAILABLE = (OSError, asyncio.TimeoutError, asyncpg.PostgresConnectionError, asyncpg.InterfaceError,
               asyncpg.CannotConnectNowError, asyncpg.TooManyConnectionsError)

_IBAN_SQL = "upper(regexp_replace(bs.iban, '\\s', '', 'g'))"

# Duplicate marks of all bookings of one account (IBAN), from scratch. A booking is a possible duplicate
# if another statement of the same IBAN that was captured earlier (tie: smaller id) has a booking with
# the same booking date, amount and purpose (both missing counts as equal, EC-8); it points to the
# matching booking of the earliest such statement. Bookings without date or amount are never compared.
_DEDUP_SQL = f"""
WITH t AS (
    SELECT bt.id, bt.document_id, bt.position, bt.booking_date, bt.amount, COALESCE(bt.purpose, '') AS purpose,
           COALESCE(d.captured, 'infinity'::timestamptz) AS captured
      FROM alice.doc_bank_transactions bt
      JOIN alice.doc_bank_statements bs ON bs.document_id = bt.document_id
      JOIN alice.doc_documents d ON d.id = bt.document_id
     WHERE {_IBAN_SQL} = $1
), marks AS (
    SELECT t.id,
           (SELECT o.id FROM t o
             WHERE o.document_id <> t.document_id
               AND o.booking_date = t.booking_date AND o.amount = t.amount AND o.purpose = t.purpose
               AND (o.captured, o.document_id) < (t.captured, t.document_id)
             ORDER BY o.captured, o.document_id, o.position
             LIMIT 1) AS original
      FROM t
)
UPDATE alice.doc_bank_transactions bt
   SET duplicate_of = marks.original
  FROM marks
 WHERE bt.id = marks.id AND bt.duplicate_of IS DISTINCT FROM marks.original
"""

_DOC_COLS = ("id", "type", "title", "summary", "tags", "document_date", "sender", "recipient", "language",
             "classification_confidence", "classification_uncertain", "summary_language_uncertain",
             "modified", "captured", "markdown_path", "locations")
_LINE_COLS = ("position", *LINE_ITEM)
_TX_COLS = ("position", *TRANSACTION, "currency")
_PG_TYPES = {"text": "text", "number": "numeric", "date": "date", "bool": "boolean", "int": "int"}
_LINE_TYPES = ["int"] + [LINE_ITEM[c] for c in LINE_ITEM]
_TX_TYPES = ["int"] + [TRANSACTION[c] for c in TRANSACTION] + ["text"]


def _insert(table: str, cols) -> str:
    return (f"INSERT INTO alice.{table} ({', '.join(cols)}) "
            f"VALUES ({', '.join(f'${i + 1}' for i in range(len(cols)))})")


def _insert_many(table: str, cols, types) -> str:
    """One statement for all rows (thousands of bookings, EC-6): unnest of one array per column."""
    arrays = ", ".join(f"${i + 2}::{_PG_TYPES[t]}[]" for i, t in enumerate(types))
    return (f"INSERT INTO alice.{table} (document_id, {', '.join(cols)}) "
            f"SELECT $1, * FROM unnest({arrays})")


class Store:
    def __init__(self, dsn: str, pool=None):
        self.dsn = dsn
        self.pool = pool

    async def connect(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=0, max_size=5, command_timeout=300,
                                                  init=_init_connection)
        return self.pool

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    async def ping(self) -> None:
        pool = await self.connect()
        await pool.fetchval("SELECT 1")

    # ---------------------------------------------------------------- per document
    async def _lock_document(self, con, source_id: str) -> None:
        await con.execute("SELECT pg_advisory_xact_lock(hashtext('alice.doc:' || $1))", source_id)

    async def _lock_accounts(self, con, ibans) -> None:
        """Same account strictly one statement after the other, also across processes (EC-4).
        Locks in sorted order: no deadlocks between two statements."""
        for key in sorted({i for i in ibans if i}):
            await con.execute("SELECT pg_advisory_xact_lock(hashtext('alice.iban:' || $1))", key)

    async def _old_ibans(self, con, source_id: str) -> set[str]:
        rows = await con.fetch(f"SELECT {_IBAN_SQL} AS iban FROM alice.doc_bank_statements bs "
                               "WHERE bs.document_id = $1", source_id)
        return {r["iban"] for r in rows if r["iban"]}

    async def _dedup(self, con, ibans) -> None:
        for key in sorted({i for i in ibans if i}):
            await con.execute(_DEDUP_SQL, key)

    async def replace(self, doc: Document, before_commit=None) -> None:
        """Replace everything of this document with `doc` in one transaction (AK-15, AK-16, AK-18, AK-19).
        `before_commit` (tests): awaited inside the transaction after all writes."""
        pool = await self.connect()
        async with pool.acquire() as con, con.transaction():
            await self._lock_document(con, doc.id)
            ibans = await self._old_ibans(con, doc.id) | {doc.iban}
            await self._lock_accounts(con, ibans)
            # detail rows, bookings and line items go with the document row (ON DELETE CASCADE)
            await con.execute("DELETE FROM alice.doc_documents WHERE id = $1", doc.id)
            await con.execute(_insert("doc_documents", _DOC_COLS), *[doc.row[c] for c in _DOC_COLS])
            if doc.detail is not None:
                cols = ("document_id", *DETAIL[doc.type])
                await con.execute(_insert(DETAIL_TABLE[doc.type], cols), doc.id,
                                  *[doc.detail[c] for c in DETAIL[doc.type]])
            if doc.line_items:
                await con.execute(_insert_many("doc_invoice_line_items", _LINE_COLS, _LINE_TYPES), doc.id,
                                  *[[r[c] for r in doc.line_items] for c in _LINE_COLS])
            if doc.transactions:
                await con.execute(_insert_many("doc_bank_transactions", _TX_COLS, _TX_TYPES), doc.id,
                                  *[[r[c] for r in doc.transactions] for c in _TX_COLS])
            await self._dedup(con, ibans)
            if before_commit is not None:
                await before_commit()

    async def remove(self, source_id: str) -> bool:
        """Deleted source: all its rows go (AK-20); marks of its account are determined anew (AK-24)."""
        pool = await self.connect()
        async with pool.acquire() as con, con.transaction():
            await self._lock_document(con, source_id)
            ibans = await self._old_ibans(con, source_id)
            await self._lock_accounts(con, ibans)
            n = await con.fetchval("WITH d AS (DELETE FROM alice.doc_documents WHERE id = $1 RETURNING 1) "
                                   "SELECT count(*) FROM d", source_id)
            await self._dedup(con, ibans)
        return bool(n)


async def _init_connection(con) -> None:
    await con.set_type_codec("jsonb", encoder=lambda v: json.dumps(v, default=str), decoder=json.loads, schema="pg_catalog")
