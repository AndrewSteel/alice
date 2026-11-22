"""Text helpers: decoding, cleaning, quality of a PDF text layer, Markdown tables, language."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .errors import PermanentError

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PUNCT = set(".,;:!?()[]{}\"'/\\@#$%&*+-=<>^~`|€£¥°§_«»„“”‘’–—…•·")


# ---------------------------------------------------------------- decoding
def decode_text(data: bytes, ext: str) -> str:
    """UTF-8 (with or without BOM), else Windows-1252, else ISO-8859-1. Binary data is an error (EC-6)."""
    if b"\x00" in data:
        raise PermanentError(f"Datei ist keine Textdatei (Inhalt passt nicht zur Endung .{ext})")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def strip_control(text: str) -> str:
    return _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


def tidy(text: str) -> str:
    """Control characters out, trailing blanks per line out, at most one empty line in a row."""
    text = strip_control(text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


# ---------------------------------------------------------------- PDF text layer quality
def _useful(c: str) -> bool:
    if c.isdigit() or c in _PUNCT:
        return True
    if unicodedata.category(c).startswith("L"):
        return "LATIN" in unicodedata.name(c, "")
    return False


def text_quality(text: str) -> float:
    """Share of readable characters. Garbage from broken font encodings (EC-1) consists of symbols,
    private-use or replacement characters. Empty text has quality 1."""
    chars = [c for c in text if not c.isspace()]
    return sum(1 for c in chars if _useful(c)) / len(chars) if chars else 1.0


def text_layer_usable(text: str, min_chars: int, min_quality: float) -> bool:
    """A page has a usable text layer if it has enough letters/digits and mostly readable characters."""
    if sum(1 for c in text if c.isalnum()) < min_chars:
        return False
    return text_quality(text) >= min_quality


# ---------------------------------------------------------------- OCR cleaning
def clean_ocr_text(text: str) -> str:
    """Remove OCR noise while keeping content (taken over from dms-extractor-ocr) and join words
    broken by a hyphen at the end of a line (AK-8)."""
    text = re.sub(r"[^\S\n\t ]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = _CONTROL.sub("", text)
    text = re.sub(r"(.)\1{4,}", lambda m: m.group(1) * 4 if m.group(1) in ".-_=" else "", text)
    text = re.sub(r"[.\-_]{5,}", "", text)
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        non_space = [c for c in stripped if not c.isspace()]
        if not non_space or len(stripped) <= 3 or sum(map(_useful, non_space)) / len(non_space) >= 0.30:
            lines.append(line.rstrip())
    text = "\n".join(lines)
    # "Rech-\nnung" → "Rechnung" (only before a lower-case letter: keeps "Ein- und Ausgaben" lists intact)
    text = re.sub(r"(\w)-\n[ \t]*([a-zäöüß])", r"\1\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------- Markdown
def _cell(value) -> str:
    text = "" if value is None else str(value)
    text = strip_control(text).strip().replace("\\", "\\\\").replace("|", "\\|")
    return re.sub(r"\n+", "<br>", text)


def md_table(rows: list[list]) -> str:
    """Rows of cells → Markdown table (first row is the header). Complete, nothing cut off (EC-3)."""
    rows = [[_cell(c) for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join(["---"] * width) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


@dataclass
class Section:
    heading: str | None
    body: str


@dataclass
class Result:
    sections: list[Section] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)
    method: str = "text"

    @property
    def empty(self) -> bool:
        return not any(s.body.strip() for s in self.sections)

    def markdown(self) -> str:
        parts = []
        for s in self.sections:
            if not s.body.strip():
                continue
            parts.append(f"## {s.heading}\n\n{s.body.strip()}" if s.heading else s.body.strip())
        return "\n\n".join(parts)


# ---------------------------------------------------------------- language
def detect_language(text: str, min_chars: int, min_probability: float = 0.90) -> str | None:
    """ISO code from statistics (no LLM); None for short or uncertain text (AK-18, EC-12)."""
    sample = re.sub(r"\s+", " ", text)[:20000]
    if sum(1 for c in sample if c.isalpha()) < min_chars:
        return None
    from langdetect import DetectorFactory, detect_langs
    from langdetect.lang_detect_exception import LangDetectException

    DetectorFactory.seed = 0  # reproducible results
    try:
        best = detect_langs(sample)[0]
    except LangDetectException:
        return None
    return best.lang if best.prob >= min_probability else None
