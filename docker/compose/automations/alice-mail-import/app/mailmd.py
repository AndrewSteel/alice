"""Mail markdown (stage extract): frontmatter fields and content part built from the archived `.eml`
and its archive entry, without LLM and without IMAP (AK-17–25)."""
from __future__ import annotations

import posixpath
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from markdownify import markdownify

from . import mime

MIN_LANGUAGE_WORDS = 20
_WORD = re.compile(r"[a-zäöüß]+")
GERMAN = frozenset("""
der die das und ist sind war waren wird werden wurde wurden für mit von den dem des ein eine einer
eines einem einen nicht auf zu im bei sich über auch als oder aus nach zum zur vom wie dass sowie
diese dieser dieses durch bis wenn noch nur mehr kein keine ihr ihre sein seine hat haben unter ich
du wir sie es mir dir uns euch mein dein unser bitte danke viele grüße gerne heute morgen
""".split())
ENGLISH = frozenset("""
the a and of to is are were be been being for with this that these those from by on at as or
it its has have had which who whom whose not no your our their his her they we you he she what when
where there here than then into about after before over under between can could should would
may might must shall do does did done any each such only very more most other some all both i me my
please thanks regards
""".split())


def detect_language(text: str) -> str | None:
    """`de` / `en` from the share of function words (AK-25); too little text → None."""
    words = _WORD.findall((text or "").lower())
    if len(words) < MIN_LANGUAGE_WORDS:
        return None
    de = sum(w in GERMAN for w in words)
    en = sum(w in ENGLISH for w in words)
    if max(de, en) < 3:
        return None
    return "de" if de >= en else "en"


def html_to_markdown(html: str) -> str:
    """Links and tables stay; images, tracking pixels, styles and scripts go (AK-19)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "img", "head", "title", "meta", "link", "noscript", "svg", "object",
                     "iframe", "embed"]):
        tag.decompose()
    md = markdownify(str(soup), heading_style="ATX", bullets="-", strip=["span", "font", "o:p"])
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def body_text(msg) -> str:
    """Text part preferred; only HTML → Markdown. Never shortened, quotes included (AK-18/20)."""
    plain, html = [], []
    for part in mime.leaves(msg):
        if part.get_content_type() == "text/plain" and mime._is_body_text(part):
            plain.append(mime.text_of(part))
        elif part.get_content_type() == "text/html" and mime._is_body_text(part):
            html.append(mime.text_of(part))
    text = "\n\n".join(t.replace("\r\n", "\n").strip("\n") for t in plain if t.strip())
    if not text.strip() and html:
        text = "\n\n".join(html_to_markdown(h) for h in html if h.strip())
    return text.strip("\n")


def _person(p: dict) -> str:
    if p.get("name") and p.get("address"):
        return f"{p['name']} <{p['address']}>"
    return p.get("address") or p.get("name") or ""


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB".replace(".", ",")
    return f"{n / 1024 / 1024:.1f} MB".replace(".", ",")


def _link(name: str, path: str) -> str:
    label = name.replace("[", "\\[").replace("]", "\\]")
    return f"[{label}](<{path}>)"


SECTION = "## Anhänge"


def attachment_section(attachments: list[dict], links: dict | None = None) -> str:
    """The section „Anhänge“: archive link per attachment; registered attachments (PROJ-124) also link
    to their markdown. `links`: absolute archive path → relative path of the attachment markdown."""
    links = links or {}
    att = [SECTION, ""]
    for a in attachments:
        line = f"- {_link(a['filename'], a['path'])} ({a['mime_type']}, {_size(a['size'])})"
        if links.get(a["path"]):
            line += f" → [Markdown](<{links[a['path']]}>)"
        att.append(line)
    return "\n".join(att)


def with_ids(attachments: list[dict], ids: dict) -> list[dict]:
    """`attachments` with the source id of every registered attachment (PROJ-124); others without `id`."""
    out = []
    for a in attachments:
        a = {k: v for k, v in a.items() if k != "id"}
        if isinstance(a.get("path"), str) and ids.get(a["path"]):
            a["id"] = ids[a["path"]]
        out.append(a)
    return out


def replace_section(content: str, section: str) -> str:
    """Content part with the section „Anhänge“ (always the last part) replaced or appended."""
    text = (content or "").rstrip("\n")
    marker = "\n" + SECTION + "\n"
    if text == SECTION or text.startswith(SECTION + "\n"):
        head = ""
    elif marker in text + "\n":
        head = (text + "\n").split(marker, 1)[0].rstrip("\n")
    else:
        head = text
    return (head + "\n\n" if head else "") + section + "\n"


def build(eml: bytes, entry: dict, archive_root: str, tz: ZoneInfo, received: datetime | None = None,
          links: dict | None = None) -> tuple[dict, str]:
    """(fields, content) for the source markdown. `entry` is the archive entry (eml_path, attachments).
    `links` (PROJ-124): absolute archive path → (source id, relative markdown path) of registered
    attachments, so a new extract (rebuild) keeps the references."""
    msg = mime.parse(eml)
    date = mime.mail_date(msg) or received
    sender = mime.addresses(msg, "From")
    fields = {
        "title": mime.subject(msg),
        "from": sender[0] if sender else None,
        "to": mime.addresses(msg, "To"),
        "cc": mime.addresses(msg, "Cc"),
        "date": date.isoformat() if date else None,
        "message_id": mime.message_id(msg),
        "in_reply_to": _first_ref(msg),
        "references": mime.references(msg),
        "archive": posixpath.join(archive_root, entry["eml_path"]),
        "attachments": [{"filename": a["filename"], "mime_type": a["mime_type"], "size": a["size"],
                         "path": posixpath.join(archive_root, a["path"])} for a in entry.get("attachments") or []],
    }
    bcc = mime.addresses(msg, "Bcc")
    if bcc:
        fields["bcc"] = bcc  # only when the mail has it (sent mails)
    text = body_text(msg)
    encrypted = mime.is_encrypted(msg)
    fields["language"] = detect_language(text)

    lines = []
    if fields["from"]:
        lines.append(f"**Von:** {_person(fields['from'])}  ")
    if fields["to"]:
        lines.append(f"**An:** {', '.join(_person(p) for p in fields['to'])}  ")
    if fields["cc"]:
        lines.append(f"**Cc:** {', '.join(_person(p) for p in fields['cc'])}  ")
    if bcc:
        lines.append(f"**Bcc:** {', '.join(_person(p) for p in bcc)}  ")
    if date:
        lines.append(f"**Datum:** {date.astimezone(tz):%d.%m.%Y %H:%M}")
    parts = ["\n".join(lines).rstrip()] if lines else []
    if encrypted:
        parts.append("_Diese Mail ist verschlüsselt. Der verschlüsselte Inhalt wurde nicht entschlüsselt._")
    if text.strip():
        parts.append(text)
    if fields["attachments"]:
        links = links or {}
        fields["attachments"] = with_ids(fields["attachments"], {p: v[0] for p, v in links.items()})
        parts.append(attachment_section(fields["attachments"], {p: v[1] for p, v in links.items()}))
    return fields, "\n\n".join(p for p in parts if p) + "\n"


def _first_ref(msg) -> str | None:
    refs = mime._MSGID.findall(mime._raw_header_text(msg.get("In-Reply-To")))
    return refs[0] if refs else None
