"""MIME handling of one mail (no IMAP, no files): identity, header decoding, real attachments vs.
embedded `cid:` images, the archived `.eml` with attachments replaced by references, and the
readable text. Everything works on the compat32 object model, so the archived mail keeps the
original headers, boundaries and part bodies unchanged.
"""
from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import errors as email_errors
from email.generator import BytesGenerator
from email.header import Header, decode_header
from email.message import Message
from email.parser import BytesParser
from email.policy import compat32
from email.utils import getaddresses, parsedate_to_datetime
from io import BytesIO
from urllib.parse import unquote

NO_SUBJECT = "(ohne Betreff)"
FATAL_DEFECTS = (email_errors.StartBoundaryNotFoundDefect, email_errors.MultipartInvariantViolationDefect,
                 email_errors.NoBoundaryInMultipartDefect)
ENCRYPTED_TYPES = ("multipart/encrypted", "application/pkcs7-mime", "application/x-pkcs7-mime")
_CID = re.compile(r"""cid:([^"'\s>)]+)""", re.I)
_BAD_NAME = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')
_MSGID = re.compile(r"<[^<>\s]+>")
NAME_MAX_BYTES = 200


class BrokenMail(Exception):
    """The MIME structure cannot be taken apart; the raw mail is archived unchanged (AK-42)."""


# ---------------------------------------------------------------- decoding
def decode_bytes(data: bytes, charset: str | None) -> str:
    """Text of a part. Wrong or unknown declarations fall back instead of failing (AK-22):
    declared charset → UTF-8 → cp1252 → latin-1 (never fails)."""
    cs = (charset or "").strip().lower() or None
    if cs in (None, "us-ascii", "ascii", "iso-8859-1", "latin-1", "latin1", "windows-1252", "cp1252"):
        # declared as latin-1/ASCII but really UTF-8 (frequent): prefer UTF-8 when it is valid
        try:
            text = data.decode("utf-8")
            if any(ord(c) > 127 for c in text) or cs in (None, "us-ascii", "ascii"):
                return text
        except UnicodeDecodeError:
            pass
    for candidate in (cs, "utf-8", "cp1252"):
        if not candidate:
            continue
        try:
            return data.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("latin-1", errors="replace")


def _raw_header_text(value) -> str:
    if isinstance(value, Header):
        return str(value)
    if isinstance(value, str):
        try:  # 8-bit header bytes come back surrogate-escaped
            return decode_bytes(value.encode("utf-8", "surrogateescape"), None)
        except UnicodeEncodeError:
            return value
    return "" if value is None else str(value)


def decode_header_value(value) -> str:
    """RFC 2047 encoded words in any charset, with fallback for wrong charsets (AK-22)."""
    if value is None:
        return ""
    try:
        parts = decode_header(value if isinstance(value, Header) else _raw_header_text(value))
    except (email_errors.HeaderParseError, ValueError, LookupError):
        return _raw_header_text(value).strip()
    out: list[str] = []
    for chunk, cs in parts:
        if isinstance(chunk, bytes):
            out.append(decode_bytes(chunk, cs))
        else:
            out.append(chunk)
    return re.sub(r"\s*\r?\n\s*", " ", "".join(out)).strip()


def addresses(msg: Message, name: str) -> list[dict]:
    values = [decode_header_value(v) for v in (msg.get_all(name) or [])]
    out = []
    for display, addr in getaddresses(values):
        if not addr and not display:
            continue
        out.append({"name": display.strip() or None, "address": addr.strip() or None})
    return out


def message_id(msg: Message) -> str | None:
    raw = _raw_header_text(msg.get("Message-ID")).strip()
    if not raw:
        return None
    m = _MSGID.search(raw)
    return m.group(0) if m else (raw.split()[0] if raw.split() else None)


def references(msg: Message) -> list[str]:
    return _MSGID.findall(_raw_header_text(msg.get("References")))


def mail_date(msg: Message) -> datetime | None:
    raw = _raw_header_text(msg.get("Date")).strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def subject(msg: Message) -> str:
    return decode_header_value(msg.get("Subject")) or NO_SUBJECT


# ---------------------------------------------------------------- identity
def _sha(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()


def _body_bytes(raw: bytes) -> bytes:
    raw = raw.replace(b"\r\n", b"\n")
    i = raw.find(b"\n\n")
    return raw[i + 2:].rstrip() if i >= 0 else b""


def source_hash(msg: Message, raw: bytes) -> tuple[str, str]:
    """(register hash, location key). One source per Message-ID (AK-7); mails without Message-ID are
    recognized by a fingerprint of sender, date, subject and content (AK-8)."""
    mid = message_id(msg)
    if mid:
        return "mid:" + _sha(mid.strip("<>").strip().lower().encode("utf-8", "surrogateescape")), mid
    head = "\n".join(_raw_header_text(msg.get(h)).strip() for h in ("From", "Date", "Subject"))
    fp = _sha(head.encode("utf-8", "surrogateescape") + b"\n\n" + _body_bytes(raw))
    return "mfp:" + fp, "fp:" + fp


# ---------------------------------------------------------------- structure
def parse(raw: bytes) -> Message:
    return BytesParser(policy=compat32).parsebytes(raw)


def leaves(msg: Message):
    """All parts, not descending into attached messages (message/*: a forwarded mail is one part)."""
    if msg.get_content_maintype() == "message":
        yield msg
        return
    if msg.is_multipart():
        payload = msg.get_payload()
        if isinstance(payload, list):
            for sub in payload:
                yield from leaves(sub)
        return
    yield msg


def all_parts(msg: Message):
    yield msg
    payload = msg.get_payload()
    if isinstance(payload, list):
        for sub in payload:
            yield from all_parts(sub)


def check_structure(msg: Message) -> None:
    for part in all_parts(msg):
        for defect in part.defects:
            if isinstance(defect, FATAL_DEFECTS):
                raise BrokenMail(f"MIME-Aufbau fehlerhaft ({defect.__class__.__name__})")


def is_encrypted(msg: Message) -> bool:
    return any(p.get_content_type() in ENCRYPTED_TYPES for p in all_parts(msg))


def part_filename(part: Message) -> str | None:
    try:
        name = part.get_filename()
    except (LookupError, ValueError, UnicodeError):
        name = None
    if name is None:
        return None
    return decode_header_value(name) or None


def _is_body_text(part: Message) -> bool:
    return (part.get_content_type() in ("text/plain", "text/html") and part_filename(part) is None
            and (part.get_content_disposition() or "inline") != "attachment")


def text_of(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        payload = b""
    return decode_bytes(payload, part.get_content_charset())


def html_cids(msg: Message) -> set[str]:
    cids: set[str] = set()
    for part in leaves(msg):
        if part.get_content_type() == "text/html" and _is_body_text(part):
            cids.update(unquote(c).strip("<>").lower() for c in _CID.findall(text_of(part)))
    return cids


def _content_id(part: Message) -> str | None:
    cid = _raw_header_text(part.get("Content-ID")).strip().strip("<>").lower()
    return cid or None


@dataclass
class Attachment:
    part: Message
    filename: str
    mime_type: str
    data: bytes
    size: int = field(init=False)

    def __post_init__(self):
        self.size = len(self.data)


def _clean_name(name: str) -> str:
    name = _BAD_NAME.sub("_", name).strip().lstrip(".").strip()
    if len(name.encode("utf-8")) > NAME_MAX_BYTES:
        stem, dot, ext = name.rpartition(".")
        ext = ext if dot and len(ext) <= 10 else ""
        stem = stem if dot and ext else name
        while len((stem + ("." + ext if ext else "")).encode("utf-8")) > NAME_MAX_BYTES:
            stem = stem[:-1]
        name = stem + ("." + ext if ext else "")
    return name


def _unique(name: str, used: set[str]) -> str:
    """rechnung.pdf, rechnung-2.pdf, rechnung-3.pdf (AK-14); case-insensitive."""
    if name.lower() not in used:
        used.add(name.lower())
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    n = 2
    while True:
        cand = f"{stem}-{n}" + (f".{ext}" if ext else "")
        if cand.lower() not in used:
            used.add(cand.lower())
            return cand
        n += 1


def _generated_name(mime_type: str, n: int) -> str:
    """EC-7: attachment without a name → name from MIME type and running number."""
    ext = {"message/rfc822": ".eml", "text/calendar": ".ics", "text/plain": ".txt"}.get(mime_type) \
        or mimetypes.guess_extension(mime_type) or ".bin"
    return f"anhang-{n}{ext}"


def _attachment_bytes(part: Message) -> bytes:
    if part.get_content_type() == "message/rfc822":
        payload = part.get_payload()
        inner = payload[0] if isinstance(payload, list) and payload else None
        if isinstance(inner, Message):
            return as_bytes(inner, crlf=False)  # the forwarded mail as it was attached (AK-13)
        return part.get_payload(decode=True) or b""
    data = part.get_payload(decode=True)
    if data is None:
        raw = part.get_payload()
        data = raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else b""
    return data


def find_attachments(msg: Message) -> list[Attachment]:
    """Real attachments (AK-12/13, EC-7, EC-9): every part with a file name that is not embedded in
    the HTML text via `cid:`, attached messages (`message/rfc822`) and calendar invitations."""
    cids = html_cids(msg)
    found: list[Attachment] = []
    used: set[str] = set()
    n = 0
    for part in leaves(msg):
        ctype = part.get_content_type()
        name = part_filename(part)
        disposition = part.get_content_disposition()
        if ctype == "message/rfc822" or ctype == "text/calendar":
            real = True
        elif name is not None or disposition == "attachment":
            cid = _content_id(part)
            real = not (cid and cid in cids)
        else:
            real = False
        if not real:
            continue
        n += 1
        clean = _clean_name(name) if name else ""
        if not clean:
            clean = _generated_name(ctype, n)
        if ctype == "message/rfc822" and not clean.lower().endswith(".eml"):
            clean += ".eml"
        found.append(Attachment(part=part, filename=_unique(clean, used), mime_type=ctype,
                                data=_attachment_bytes(part)))
    return found


def replace_with_reference(att: Attachment, rel_path: str) -> None:
    """The attachment part becomes a `message/external-body` reference to the archived file
    (RFC 2017, access type local-file); the binary data leaves the `.eml` (AK-11)."""
    part = att.part
    inner = Message()
    for key in ("Content-Type", "Content-Disposition", "Content-ID", "Content-Description"):
        value = part.get(key)
        if value is not None:
            inner[key] = value
    if inner.get("Content-Type") is None:
        inner["Content-Type"] = att.mime_type
    inner.set_payload("")
    for key in [k for k in part.keys() if k.lower().startswith("content-") or k.lower() == "mime-version"]:
        del part[key]
    if part.get("MIME-Version") is None and part.get("From") is not None:
        part["MIME-Version"] = "1.0"
    part.add_header("Content-Type", "message/external-body", access_type="local-file",
                    name=("utf-8", "", rel_path))
    part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", att.filename))
    part.set_payload([inner])


def as_bytes(msg: Message, crlf: bool) -> bytes:
    buf = BytesIO()
    policy = compat32.clone(linesep="\r\n" if crlf else "\n")
    BytesGenerator(buf, mangle_from_=False, maxheaderlen=0, policy=policy).flatten(msg)
    return buf.getvalue()


@dataclass
class Prepared:
    """Result of taking a mail apart for the archive."""
    hash: str
    location_key: str           # Message-ID or fingerprint, stored as message_id of the location
    subject: str
    date: datetime | None
    size: int
    attachments: list[Attachment]
    broken: str | None
    msg: Message | None

    def archived_eml(self, attachment_dir: str, raw: bytes) -> bytes:
        """The `.eml` for the archive: attachments replaced by references to `<attachment_dir>/<name>`.
        Broken mails stay byte for byte (AK-42)."""
        if self.broken or not self.attachments or self.msg is None:
            return raw
        for att in self.attachments:
            replace_with_reference(att, f"{attachment_dir}/{att.filename}")
        return as_bytes(self.msg, crlf=b"\r\n" in raw[:4096])


def prepare(raw: bytes) -> Prepared:
    """Parse a raw mail. Never raises for broken structure: `broken` holds the cause instead."""
    try:
        msg = parse(raw)
    except Exception as exc:  # the parser is lenient; this is the last resort
        fp = "mfp:" + _sha(raw)
        return Prepared(fp, "fp:" + fp[4:], NO_SUBJECT, None, len(raw), [], f"Mail nicht lesbar ({exc.__class__.__name__})", None)
    h, key = source_hash(msg, raw)
    subj = subject(msg)
    date = mail_date(msg)
    try:
        check_structure(msg)
        atts = find_attachments(msg)
        broken = None
    except BrokenMail as exc:
        atts, broken = [], str(exc)
    except Exception as exc:
        atts, broken = [], f"MIME-Aufbau nicht zerlegbar ({exc.__class__.__name__})"
    return Prepared(h, key, subj, date, len(raw), atts, broken, msg)
