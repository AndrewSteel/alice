"""Rule based checks without LLM: value normalisation, IBAN/ISIN check digits, balance check, title.

Values that cannot be read unambiguously become None: nothing is guessed (spec "Felder").
"""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

TYPES = ("Invoice", "BankStatement", "Contract", "SecuritySettlement", "Document")
TRANSACTION_TYPES = ("buy", "sell", "dividend", "distribution")
TITLE_MAX = 80

COMMON = {"document_date": "date", "sender": "text", "recipient": "text", "tags": "tags"}
TYPE_FIELDS = {
    "Invoice": {"invoice_number": "text", "invoice_date": "date", "due_date": "date", "amount_gross": "amount",
                "amount_net": "amount", "vat_rate": "number", "currency": "currency", "line_items": "line_items"},
    "BankStatement": {"bank_name": "text", "account_holder": "text", "iban": "iban", "period_from": "date",
                      "period_to": "date", "opening_balance": "amount", "closing_balance": "amount",
                      "currency": "currency", "transactions": "transactions"},
    "SecuritySettlement": {"bank": "text", "depot_number": "text", "transaction_date": "date",
                           "security_name": "text", "isin": "isin", "transaction_type": "transaction_type",
                           "quantity": "number", "price": "amount", "settlement_amount": "amount",
                           "currency": "currency"},
    "Contract": {"contract_type": "text", "contract_partner": "text", "sign_date": "date", "start_date": "date",
                 "end_date": "date", "notice_period": "text", "monthly_cost": "amount", "annual_cost": "amount",
                 "currency": "currency"},
    "Document": {},
}
LINE_ITEM = {"description": "text", "quantity": "number", "amount": "amount"}
TRANSACTION = {"booking_date": "date", "value_date": "date", "counterparty": "text", "purpose": "text",
               "amount": "amount"}


def field_spec(doc_type: str) -> dict:
    return {**COMMON, **TYPE_FIELDS[doc_type]}


# ---------------------------------------------------------------- single values
def text(value) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$")
_DE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


def parse_date(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    m = _ISO.match(value)
    if m:
        y, mo, d = m.groups()
    else:
        m = _DE.match(value)
        if not m:
            return None
        d, mo, y = m.groups()
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


def parse_number(value) -> float | None:
    """Number from a JSON number or a German/English formatted string; ambiguous → None (EC-5)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value and abs(value) != float("inf") else None
    if not isinstance(value, str):
        return None
    s = value.strip().replace("−", "-").replace(" ", " ")
    sign = 1
    m = re.search(r"\s*\b([SH])$", s)  # Soll (debit) / Haben (credit) on bank statements
    if m:
        sign = -1 if m.group(1) == "S" else 1
        s = s[:m.start()]
    s = re.sub(r"(?i)\s*(eur|euro|usd|chf|gbp|€|\$|%)\s*", "", s).strip()
    s = s.replace(" ", "").replace("'", "")
    if s.endswith("-"):
        s, sign = s[:-1], -sign
    elif s.endswith("+"):
        s = s[:-1]
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("-"):
        s, sign = s[1:], -sign
    if not re.fullmatch(r"[\d.,]+", s) or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        int_part, frac = s.rsplit(dec, 1)
        if not re.fullmatch(r"\d{1,3}(\%s\d{3})*" % thou, int_part) or not frac.isdigit():
            return None
        num = float(int_part.replace(thou, "") + "." + frac)
    elif "," in s:
        if s.count(",") > 1:
            if not re.fullmatch(r"\d{1,3}(,\d{3})+", s):
                return None
            num = float(s.replace(",", ""))
        else:
            int_part, frac = s.split(",")
            if not int_part.isdigit() or not frac.isdigit():
                return None
            num = float(f"{int_part}.{frac}")
    elif "." in s:
        if s.count(".") > 1:
            if not re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
                return None
            num = float(s.replace(".", ""))
        else:
            int_part, frac = s.split(".")
            if not int_part.isdigit() or not frac.isdigit():
                return None
            if len(frac) == 3:  # "1.234": thousands (DE) or decimal (EN) → ambiguous
                return None
            num = float(f"{int_part}.{frac}")
    else:
        num = float(s)
    return sign * num


def parse_amount(value) -> float | None:
    num = parse_number(value)
    return round(num, 2) if num is not None else None


_CURRENCY_SYMBOLS = {"€": "EUR", "EURO": "EUR", "$": "USD", "£": "GBP", "FR.": "CHF", "SFR": "CHF"}


def currency(value) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().upper()
    v = _CURRENCY_SYMBOLS.get(v, v)
    return v if re.fullmatch(r"[A-Z]{3}", v) else None


def iban(value) -> str | None:
    """Normalized IBAN (no spaces, upper case) if the check digits are valid (AK-16)."""
    if not isinstance(value, str):
        return None
    v = re.sub(r"[\s-]", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", v):
        return None
    digits = "".join(str(int(c, 36)) for c in v[4:] + v[:4])
    return v if int(digits) % 97 == 1 else None


def isin(value) -> str | None:
    """ISIN if the Luhn check digit over the expanded characters is valid (AK-16)."""
    if not isinstance(value, str):
        return None
    v = re.sub(r"\s", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", v):
        return None
    digits = "".join(str(int(c, 36)) for c in v)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return v if total % 10 == 0 else None


def tags(value) -> list[str] | None:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for item in value:
        t = text(item)
        if t and t.lower() not in (o.lower() for o in out):
            out.append(t)
    return out[:8] or None


def _record(value, spec: dict) -> dict | None:
    if not isinstance(value, dict):
        return None
    rec = {k: convert(kind, value.get(k)) for k, kind in spec.items()}
    return rec if any(v is not None for v in rec.values()) else None


def _records(value, spec: dict) -> list[dict] | None:
    if not isinstance(value, list):
        return None
    return [r for r in (_record(v, spec) for v in value) if r is not None]


def convert(kind: str, value):
    if kind == "text":
        return text(value)
    if kind == "date":
        return parse_date(value)
    if kind == "amount":
        return parse_amount(value)
    if kind == "number":
        return parse_number(value)
    if kind == "currency":
        return currency(value)
    if kind == "iban":
        return iban(value)
    if kind == "isin":
        return isin(value)
    if kind == "tags":
        return tags(value)
    if kind == "transaction_type":
        v = text(value)
        return v.lower() if v and v.lower() in TRANSACTION_TYPES else None
    if kind == "line_items":
        return _records(value, LINE_ITEM)
    if kind == "transactions":
        return _records(value, TRANSACTION)
    raise ValueError(kind)


def normalize_fields(doc_type: str, raw) -> dict:
    """Exactly the common fields and those of `doc_type`, in table order; invalid → None (AK-12–14)."""
    raw = raw if isinstance(raw, dict) else {}
    return {name: convert(kind, raw.get(name)) for name, kind in field_spec(doc_type).items()}


def transactions(raw) -> list[dict] | None:
    return _records(raw, TRANSACTION)


# ---------------------------------------------------------------- bank statements
def _same_booking(a: dict, b: dict) -> bool:
    def purpose(t):
        return " ".join((t.get("purpose") or "").lower().split())
    return (a.get("booking_date") == b.get("booking_date") and a.get("amount") == b.get("amount")
            and purpose(a) == purpose(b))


def merge_transactions(chunks: list[list[dict]]) -> list[dict]:
    """Transactions of all sections in document order. The same booking as last of one section and
    first of the next is taken once; equal bookings inside a section stay (AK-27)."""
    out: list[dict] = []
    prev_last: dict | None = None
    for txs in chunks:
        if prev_last is not None and txs and _same_booking(prev_last, txs[0]):
            txs = txs[1:]
        out.extend(txs)
        prev_last = txs[-1] if txs else None
    return out


def balance_check(fields: dict) -> dict:
    """Without LLM: opening + sum of bookings = closing (tolerance 0.01); mismatch → flag + difference."""
    opening, closing = fields.get("opening_balance"), fields.get("closing_balance")
    if opening is None or closing is None:
        return {}
    total = sum(t["amount"] for t in fields.get("transactions") or [] if t.get("amount") is not None)
    diff = round(closing - (opening + total), 2)
    if abs(diff) > 0.01:
        return {"balance_mismatch": True, "balance_difference": diff}
    return {}


# ---------------------------------------------------------------- title
_DATE_PREFIX = re.compile(r"^\s*\d{4}-\d{2}-\d{2}(?:[ T_]\d{2}[.:]\d{2}(?:[.:]\d{2})?)?\s*[-–—:|]?\s*")


def _when(value, tz: ZoneInfo) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def title_prefix(modified, captured, timezone: str) -> str:
    """`YYYY-MM-DD hh.mm.ss` of the original's change time in local time; without valid `modified`
    the capture time (EC-6)."""
    tz = ZoneInfo(timezone)
    dt = _when(modified, tz) or _when(captured, tz)
    return dt.strftime("%Y-%m-%d %H.%M.%S") if dt else ""


def clean_title(value) -> str:
    t = text(value) or ""
    t = t.lstrip("# ").strip()
    while True:  # no double prefix if the LLM sends one (EC-8)
        stripped = _DATE_PREFIX.sub("", t, count=1)
        if stripped == t:
            break
        t = stripped
    if len(t) > TITLE_MAX:
        cut = t[:TITLE_MAX + 1]
        space = cut.rfind(" ")
        t = cut[:space] if space > 0 else t[:TITLE_MAX]
        t = t.rstrip(" -–—:;,.")
    return t


def build_title(llm_title, fallback: str, modified, captured, timezone: str) -> str:
    t = clean_title(llm_title) or clean_title(fallback) or "Dokument"
    prefix = title_prefix(modified, captured, timezone)
    return f"{prefix} {t}" if prefix else t
