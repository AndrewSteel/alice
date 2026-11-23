"""Rule based checks without LLM: values, check digits, balance, title (AK-14, AK-16, AK-18, AK-28–30, EC-5–8)."""
import pytest

from app import normalize as n

VALID_IBAN = "DE89370400440532013000"  # public example IBAN
VALID_ISIN = "US0378331005"  # public example ISIN


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-14", "2026-10-14"), ("14.10.2026", "2026-10-14"), ("1.2.2026", "2026-02-01"),
    ("2026-10-14T00:00:00", "2026-10-14"), ("31.13.2026", None), ("2026-02-30", None), ("Oktober", None),
    (20261014, None), (None, None),
])
def test_dates(raw, expected):
    assert n.parse_date(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (12.5, 12.5), (3, 3.0), ("1.234,56", 1234.56), ("-12,00", -12.0), ("12,00 S", -12.0), ("12,00 H", 12.0),
    ("12,00-", -12.0), ("1,234.56", 1234.56), ("1.234.567", 1234567.0), ("12,5 €", 12.5), ("EUR 99.90", 99.9),
    ("1.234", None), ("ca. zwanzig", None), ("", None), (True, None), ("12,3,4", None),
])
def test_amounts(raw, expected):  # EC-5, AK-14
    assert n.parse_amount(raw) == expected


def test_iban_isin():  # AK-16
    assert n.iban("de89 3704 0044 0532 0130 00") == VALID_IBAN
    assert n.iban("DE89370400440532013001") is None
    assert n.iban("kein iban") is None
    assert n.isin(VALID_ISIN) == VALID_ISIN
    assert n.isin("us 0378331005") == VALID_ISIN
    assert n.isin("US0378331006") is None


def test_currency_tags_enum():
    assert n.currency("eur") == "EUR" and n.currency("€") == "EUR" and n.currency("Euro") == "EUR"
    assert n.currency("Euronen") is None
    assert n.tags(["Strom", "strom", " Abrechnung ", "", 3]) == ["Strom", "Abrechnung", "3"]
    assert len(n.tags([f"t{i}" for i in range(12)])) == 8
    assert n.convert("transaction_type", "Buy") == "buy"
    assert n.convert("transaction_type", "swap") is None


def test_normalize_fields_exact_set():  # AK-12, AK-13, AK-14
    f = n.normalize_fields("Contract", {"contract_type": "Strom", "invoice_number": "R-1", "start_date": "31.13.2026",
                                        "monthly_cost": "ca. zwanzig", "annual_cost": "240,00"})
    assert list(f) == ["document_date", "sender", "recipient", "tags", "contract_type", "contract_partner",
                       "sign_date", "start_date", "end_date", "notice_period", "monthly_cost", "annual_cost",
                       "currency"]
    assert f["contract_type"] == "Strom" and f["start_date"] is None and f["monthly_cost"] is None
    assert f["annual_cost"] == 240.0
    assert list(n.normalize_fields("Document", "kaputt")) == ["document_date", "sender", "recipient", "tags"]


def test_line_items():
    f = n.normalize_fields("Invoice", {"line_items": [{"description": "Strom", "quantity": "2", "amount": "10,50"},
                                                      {"description": None}, "x"]})
    assert f["line_items"] == [{"description": "Strom", "quantity": 2.0, "amount": 10.5}]


def tx(d, amount, purpose="Miete"):
    return {"booking_date": d, "value_date": d, "counterparty": "X", "purpose": purpose, "amount": amount}


def test_merge_transactions():  # AK-27
    a = [tx("2026-10-01", -10.0), tx("2026-10-02", -5.0, "Kaffee"), tx("2026-10-02", -5.0, "Kaffee")]
    b = [tx("2026-10-02", -5.0, " kaffee "), tx("2026-10-03", 100.0)]
    c = [tx("2026-10-04", 1.0)]
    out = n.merge_transactions([a, b, [], c])
    assert out == a + [b[1], c[0]]  # duplicate at the border once, equal ones inside a section both kept


def test_balance():  # AK-28–30
    txs = [tx("2026-10-01", -200.0), tx("2026-10-02", 50.0)]
    assert n.balance_check({"opening_balance": 1000.0, "closing_balance": 850.0, "transactions": txs}) == {}
    assert n.balance_check({"opening_balance": 1000.0, "closing_balance": 900.0, "transactions": txs}) == {
        "balance_mismatch": True, "balance_difference": 50.0}
    assert n.balance_check({"opening_balance": None, "closing_balance": 900.0, "transactions": txs}) == {}
    assert n.balance_check({"opening_balance": 10.0, "closing_balance": 10.0, "transactions": []}) == {}


def test_title():  # AK-17, AK-18, EC-6, EC-7, EC-8
    tz = "Europe/Berlin"
    assert n.build_title("Stromrechnung Stadtwerke Oktober 2026", "x.pdf", "2026-10-14T07:32:11+00:00", None, tz) \
        == "2026-10-14 09.32.11 Stromrechnung Stadtwerke Oktober 2026"
    assert n.build_title("2026-10-14 09.32.11 Stromrechnung", "x.pdf", "2026-10-14T07:32:11+00:00", None, tz) \
        == "2026-10-14 09.32.11 Stromrechnung"
    assert n.build_title("2026-10-01 – Stromrechnung", "x", "kaputt", "2026-11-01T10:00:00+00:00", tz) \
        == "2026-11-01 11.00.00 Stromrechnung"
    long = "Sehr " * 30 + "lang"
    t = n.build_title(long, "x", "2026-10-14T07:32:11+00:00", None, tz)
    rest = t[len("2026-10-14 09.32.11 "):]
    assert len(rest) <= 80 and rest.endswith("Sehr") and not rest.endswith(" ")
    assert n.build_title("", "scan.pdf", None, None, tz) == "scan.pdf"
    assert n.build_title("Rechnung: A/B 🎉", "x", None, None, tz) == "Rechnung: A/B 🎉"
