"""Frontmatter → typed rows, without a database (AK-8, AK-11, AK-27, EC-7, EC-9)."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.convert import InvalidValue, convert, iban_key

from .conftest import IBAN_A, make_isin


def fm(doc_type, fields, **top):
    return {"id": "abcdefghijkl", "type": doc_type, "title": "T", "summary": "S", "language": "de",
            "classification": {"confidence": Decimal("0.93"), "uncertain": False},
            "summary_language_uncertain": False, "modified": "2026-10-14T07:32:11+00:00",
            "captured": "2026-11-05T10:00:00+00:00", "locations": [{"path": "/mnt/nas/a.pdf"}],
            "fields": fields, **top}


def test_invoice_types_exact():
    d = convert("abcdefghijkl", "documents/x.md", fm("Invoice", {
        "invoice_number": 4711, "invoice_date": "2026-10-14", "due_date": None, "amount_gross": Decimal("119.00"),
        "amount_net": 100, "vat_rate": Decimal("19.0"), "currency": "EUR", "tags": ["strom"],
        "line_items": [{"description": "Arbeitspreis", "quantity": Decimal("0.000123"), "amount": "1250000.00"}]}))
    assert d.row["captured"] == datetime(2026, 11, 5, 10, tzinfo=timezone.utc)
    assert d.row["classification_confidence"] == Decimal("0.93") and d.row["tags"] == ["strom"]
    assert d.detail["invoice_number"] == "4711" and d.detail["invoice_date"] == date(2026, 10, 14)
    assert d.detail["due_date"] is None and d.detail["amount_net"] == Decimal(100)
    assert d.line_items == [{"position": 1, "description": "Arbeitspreis", "quantity": Decimal("0.000123"),
                             "amount": Decimal("1250000.00")}]


def test_document_has_no_detail_and_old_schema_missing_fields_are_null():  # EC-9
    d = convert("abcdefghijkl", "p.md", {"type": "Document", "title": "T", "locations": None})
    assert d.detail is None and d.row["summary"] is None and d.row["tags"] is None
    assert d.row["locations"] == [] and d.row["classification_uncertain"] is None
    d = convert("abcdefghijkl", "p.md", {"type": "Contract", "fields": {"contract_partner": "Stadtwerke"}})
    assert d.detail["contract_partner"] == "Stadtwerke" and d.detail["monthly_cost"] is None


def test_bank_statement_bookings_get_currency_and_position():
    d = convert("abcdefghijkl", "p.md", fm("BankStatement", {
        "iban": IBAN_A, "currency": "EUR", "balance_mismatch": True, "balance_difference": Decimal("50.00"),
        "transactions": [{"booking_date": "2026-10-01", "amount": Decimal("-12.30")},
                         {"booking_date": "2026-10-02", "amount": 5, "purpose": None}]}))
    assert [t["position"] for t in d.transactions] == [1, 2]
    assert all(t["currency"] == "EUR" for t in d.transactions)
    assert d.detail["balance_mismatch"] is True and d.detail["balance_difference"] == Decimal("50.00")
    assert d.iban == IBAN_A


def test_float_values_are_kept_exact():  # EC-7 (a float can only come from a direct call)
    d = convert("abcdefghijkl", "p.md", fm("SecuritySettlement", {"quantity": 0.000123, "isin": make_isin()}))
    assert d.detail["quantity"] == Decimal("0.000123")


@pytest.mark.parametrize("fields, name", [
    ({"amount_gross": "zwölf"}, "fields.amount_gross"),
    ({"invoice_date": "31.13.2026"}, "fields.invoice_date"),
    ({"invoice_date": "2026-13-31"}, "fields.invoice_date"),
    ({"amount_gross": "12,50"}, "fields.amount_gross"),
    ({"amount_gross": True}, "fields.amount_gross"),
    ({"line_items": "drei Positionen"}, "fields.line_items"),
    ({"line_items": [{"amount": "x"}]}, "fields.line_items[0].amount"),
    ({"tags": "strom"}, "fields.tags"),
])
def test_invalid_values_name_field_and_value(fields, name):  # AK-27
    with pytest.raises(InvalidValue) as exc:
        convert("abcdefghijkl", "p.md", fm("Invoice", fields))
    assert exc.value.field == name and name in str(exc.value)
    value = next(iter(fields.values()))
    if isinstance(value, str):
        assert value in str(exc.value)


def test_invalid_transactions_and_type():
    with pytest.raises(InvalidValue, match="fields.transactions") as exc:
        convert("abcdefghijkl", "p.md", fm("BankStatement", {"transactions": "zehn Buchungen"}))
    assert "zehn Buchungen" in str(exc.value)
    with pytest.raises(InvalidValue, match="Feld type = 'Quittung'"):
        convert("abcdefghijkl", "p.md", fm("Quittung", {}))
    with pytest.raises(InvalidValue, match="Feld fields"):
        convert("abcdefghijkl", "p.md", fm("Invoice", "kaputt"))


def test_iban_key():
    spaced = " " + " ".join(IBAN_A[i:i + 4] for i in range(0, len(IBAN_A), 4)).lower() + " "
    assert iban_key(spaced) == IBAN_A
    assert iban_key(None) is None and iban_key("") is None
