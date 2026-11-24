"""Frontmatter → typed rows. Strict: a value that cannot be read unambiguously raises InvalidValue
naming field and value (AK-27); nothing is guessed, `null` stays `None` (AK-11), missing fields of
older schema versions are `None` (EC-9). No calculations, no enrichment: 1:1 from the frontmatter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

TYPES = ("Invoice", "BankStatement", "SecuritySettlement", "Contract", "Document")

# detail columns per type: column -> kind (column names = frontmatter field names)
DETAIL = {
    "Invoice": {"invoice_number": "text", "invoice_date": "date", "due_date": "date", "amount_gross": "number",
                "amount_net": "number", "vat_rate": "number", "currency": "text"},
    "BankStatement": {"bank_name": "text", "account_holder": "text", "iban": "text", "period_from": "date",
                      "period_to": "date", "opening_balance": "number", "closing_balance": "number",
                      "currency": "text", "balance_mismatch": "bool", "balance_difference": "number"},
    "SecuritySettlement": {"bank": "text", "depot_number": "text", "transaction_date": "date",
                           "security_name": "text", "isin": "text", "transaction_type": "text",
                           "quantity": "number", "price": "number", "settlement_amount": "number",
                           "currency": "text"},
    "Contract": {"contract_type": "text", "contract_partner": "text", "sign_date": "date", "start_date": "date",
                 "end_date": "date", "notice_period": "text", "monthly_cost": "number", "annual_cost": "number",
                 "currency": "text"},
    "Document": {},
}
DETAIL_TABLE = {"Invoice": "doc_invoices", "BankStatement": "doc_bank_statements",
                "SecuritySettlement": "doc_security_settlements", "Contract": "doc_contracts"}
LINE_ITEM = {"description": "text", "quantity": "number", "amount": "number"}
TRANSACTION = {"booking_date": "date", "value_date": "date", "counterparty": "text", "purpose": "text",
               "amount": "number"}

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InvalidValue(Exception):
    """Invalid value in the frontmatter; the message names field and value (shown to humans)."""

    def __init__(self, name: str, value, reason: str):
        shown = repr(value)
        if len(shown) > 200:
            shown = shown[:200] + "…"
        super().__init__(f"Ungültiger Wert im Frontmatter: Feld {name} = {shown} {reason}")
        self.field = name


@dataclass
class Document:
    id: str
    type: str
    row: dict                      # columns of alice.doc_documents
    detail: dict | None = None     # columns of the detail table of the type
    line_items: list[dict] = field(default_factory=list)
    transactions: list[dict] = field(default_factory=list)

    @property
    def iban(self) -> str | None:
        return iban_key(self.detail.get("iban")) if self.type == "BankStatement" and self.detail else None


def iban_key(value: str | None) -> str | None:
    """IBAN as compared for duplicates: without spaces, upper case."""
    if not value:
        return None
    key = re.sub(r"\s", "", value).upper()
    return key or None


# ---------------------------------------------------------------- single values
def text(name: str, value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise InvalidValue(name, value, "ist kein Text")
    if isinstance(value, (int, Decimal, float)):  # e.g. an invoice number YAML read as a number
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise InvalidValue(name, value, "ist kein Text")


def number(name: str, value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise InvalidValue(name, value, "ist keine Zahl")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        result = Decimal(repr(value))
    elif isinstance(value, str) and _NUMBER.match(value.strip()):
        try:
            result = Decimal(value.strip())
        except InvalidOperation:
            raise InvalidValue(name, value, "ist keine Zahl") from None
    else:
        raise InvalidValue(name, value, "ist keine Zahl (erwartet z. B. 1234.56)")
    if not result.is_finite():
        raise InvalidValue(name, value, "ist keine endliche Zahl")
    return result


def to_date(name: str, value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise InvalidValue(name, value, "ist kein Datum (erwartet JJJJ-MM-TT)")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _DATE.match(value.strip()):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise InvalidValue(name, value, "ist kein gültiges Datum (erwartet JJJJ-MM-TT)")


def timestamp(name: str, value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            raise InvalidValue(name, value, "ist kein gültiger Zeitpunkt") from None
    else:
        raise InvalidValue(name, value, "ist kein gültiger Zeitpunkt")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def boolean(name: str, value) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise InvalidValue(name, value, "ist kein Wahrheitswert (true/false)")


def tags(name: str, value) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise InvalidValue(name, value, "ist keine Liste")
    return [text(f"{name}[{i}]", v) for i, v in enumerate(value) if v is not None]


_CONVERT = {"text": text, "number": number, "date": to_date, "bool": boolean}


def _block(name: str, value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidValue(name, value, "ist kein Block (Schlüssel: Wert)")
    return value


def _records(name: str, value, spec: dict) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InvalidValue(name, value, "ist keine Liste")
    out = []
    for i, item in enumerate(value):
        rec = _block(f"{name}[{i}]", item)
        out.append({"position": i + 1,
                    **{col: _CONVERT[kind](f"{name}[{i}].{col}", rec.get(col)) for col, kind in spec.items()}})
    return out


# ---------------------------------------------------------------- whole frontmatter
def convert(source_id: str, path: str, fm: dict) -> Document:
    """All rows of one document from its frontmatter (AK-7–13)."""
    doc_type = fm.get("type")
    if doc_type not in TYPES:
        raise InvalidValue("type", doc_type, f"ist kein bekannter Dokumenttyp ({', '.join(TYPES)})")
    fields = _block("fields", fm.get("fields"))
    classification = _block("classification", fm.get("classification"))
    locations = fm.get("locations")
    if locations is None:
        locations = []
    if not isinstance(locations, list):
        raise InvalidValue("locations", locations, "ist keine Liste")
    row = {
        "id": source_id,
        "type": doc_type,
        "title": text("title", fm.get("title")),
        "summary": text("summary", fm.get("summary")),
        "tags": tags("fields.tags", fields.get("tags")),
        "document_date": to_date("fields.document_date", fields.get("document_date")),
        "sender": text("fields.sender", fields.get("sender")),
        "recipient": text("fields.recipient", fields.get("recipient")),
        "language": text("language", fm.get("language")),
        "classification_confidence": number("classification.confidence", classification.get("confidence")),
        "classification_uncertain": boolean("classification.uncertain", classification.get("uncertain")),
        "summary_language_uncertain": boolean("summary_language_uncertain", fm.get("summary_language_uncertain")),
        "modified": timestamp("modified", fm.get("modified")),
        "captured": timestamp("captured", fm.get("captured")),
        "markdown_path": path,
        "locations": locations,
    }
    doc = Document(id=source_id, type=doc_type, row=row)
    spec = DETAIL[doc_type]
    if doc_type != "Document":
        doc.detail = {col: _CONVERT[kind](f"fields.{col}", fields.get(col)) for col, kind in spec.items()}
    if doc_type == "Invoice":
        doc.line_items = _records("fields.line_items", fields.get("line_items"), LINE_ITEM)
    if doc_type == "BankStatement":
        doc.transactions = _records("fields.transactions", fields.get("transactions"), TRANSACTION)
        for t in doc.transactions:
            t["currency"] = doc.detail["currency"]
    return doc
