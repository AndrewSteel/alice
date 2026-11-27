"""Classification + field extraction of one source markdown (PROJ-118).

Returns the frontmatter fields to write; nothing is written here. All LLM calls of a source happen
before the single write of the worker, so nothing is half written (spec "Nichts halb geschrieben").
"""
from __future__ import annotations

import logging
import posixpath
import re
from dataclasses import dataclass

from . import language, normalize, prompts
from .config import Settings
from .llm import InvalidAnswer, LlmClient
from .normalize import TYPES

logger = logging.getLogger("alice-document-classify")

_PAGE = re.compile(r"^## Seite (\d+)[ \t]*$", re.M)


class PermanentError(Exception):
    """Cannot go away by retrying (e.g. unknown hand-set type) → failed_permanent."""


@dataclass
class Section:
    text: str
    where: str


# ---------------------------------------------------------------- sections of a bank statement
def _split_lines(text: str, size: int) -> list[str]:
    parts, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:  # a single overlong line
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:size])
            line = line[size:]
        if cur and len(cur) + len(line) > size:
            parts.append(cur)
            cur = ""
        cur += line
    if cur.strip():
        parts.append(cur)
    return [p for p in parts if p.strip()]


def sections(content: str, size: int) -> list[Section]:
    """Along the page marks `## Seite <n>` (PROJ-117), pages grouped up to `size` characters;
    without page marks by size at line boundaries (EC-3)."""
    marks = list(_PAGE.finditer(content))
    if not marks:
        parts = _split_lines(content, size)
        return [Section(p, f"Abschnitt {i + 1} von {len(parts)}") for i, p in enumerate(parts)]
    pages: list[tuple[str, str]] = []
    for i, m in enumerate(marks):
        start = 0 if i == 0 else m.start()  # text before the first mark belongs to the first page
        end = marks[i + 1].start() if i + 1 < len(marks) else len(content)
        pages.append((m.group(1), content[start:end]))
    out: list[Section] = []
    group: list[tuple[str, str]] = []

    def flush():
        if group:
            first, last = group[0][0], group[-1][0]
            where = f"Seite {first}" if first == last else f"Seite {first}–{last}"
            out.append(Section("".join(t for _, t in group), where))
            group.clear()

    for no, text in pages:
        if len(text) > size:
            flush()
            pieces = _split_lines(text, size)
            for j, piece in enumerate(pieces):
                out.append(Section(piece, f"Seite {no}" + (f", Teil {j + 1}" if len(pieces) > 1 else "")))
            continue
        if group and sum(len(t) for _, t in group) + len(text) > size:
            flush()
        group.append((no, text))
    flush()
    return out


# ---------------------------------------------------------------- answer readers
def read_classification(obj: dict) -> tuple[str, float]:
    raw = obj.get("type")
    match = next((t for t in TYPES if isinstance(raw, str) and raw.strip().lower() == t.lower()), None)
    if match is None:
        raise InvalidAnswer("Typ fehlt oder ist kein bekannter Dokumenttyp" + (f" ({raw!r})" if raw else ""))
    conf = normalize.parse_number(obj.get("confidence"))
    conf = 0.0 if conf is None else min(1.0, max(0.0, conf))
    return match, conf


def read_extraction(obj: dict) -> dict:
    fields = obj.get("fields")
    if not isinstance(fields, dict):
        fields = {k: v for k, v in obj.items() if k not in ("title", "summary")}
    title = obj.get("title") if isinstance(obj.get("title"), str) else ""
    summary = obj.get("summary") if isinstance(obj.get("summary"), str) else ""
    return {"title": title.strip(), "summary": " ".join(summary.split()), "fields": fields}


def read_transactions(obj: dict) -> list[dict]:
    txs = obj.get("transactions")
    if not isinstance(txs, list):
        raise InvalidAnswer("Buchungsliste fehlt")
    return normalize.transactions(txs) or []


def original_name(fm: dict) -> str:
    for loc in fm.get("locations") or []:
        if isinstance(loc, dict) and loc.get("path"):
            return posixpath.basename(loc["path"])
    return str(fm.get("title") or "")


# ---------------------------------------------------------------- classifier
class Classifier:
    def __init__(self, settings: Settings, llm: LlmClient):
        self.s = settings
        self.llm = llm

    async def _ask(self, step: str, system: str, user: str, temperature: float, read):
        try:
            return await self.llm.ask(system, user, temperature, read)
        except InvalidAnswer as exc:
            raise InvalidAnswer(f"Ungültige Antwort des LLM ({step}, auch im zweiten Versuch): {exc}") from None

    async def classify(self, head: str, lang: str | None, mail: dict | None = None) -> tuple[str, float, bool]:
        """Temperature 0 first; below the threshold a second try with higher temperature, the higher
        confidence wins (tie: the second) (AK-7–9)."""
        system, user = prompts.classify(head, lang, mail)
        best = await self._ask("Klassifizierung", system, user, 0.0, read_classification)
        if best[1] < self.s.confidence_threshold:
            try:
                second = await self.llm.ask(system, user, self.s.retry_temperature, read_classification)
            except InvalidAnswer:
                second = None  # the valid first result stays
            if second is not None and second[1] >= best[1]:
                best = second
        return best[0], best[1], best[1] < self.s.confidence_threshold

    async def extract(self, doc_type: str, head: str, lang: str | None,
                      mail: dict | None = None) -> tuple[dict, bool]:
        """Fields, title, summary; German check with one stricter second try (AK-21–24)."""
        system, user = prompts.extract(doc_type, head, lang, mail=mail)
        data = await self._ask("Felder", system, user, 0.0, read_extraction)
        if not language.suspicious(data["title"], data["summary"], self.s.language_threshold):
            return data, False
        system, user = prompts.extract(doc_type, head, lang, strict_german=True, mail=mail)
        data = await self._ask("Felder, Deutsch-Vorgabe", system, user, 0.0, read_extraction)
        return data, language.suspicious(data["title"], data["summary"], self.s.language_threshold)

    async def transactions(self, content: str, lang: str | None, progress=None) -> list[dict]:
        """Bookings over the whole content, section by section; one invalid section fails the source (AK-31)."""
        parts = sections(content, self.s.chunk_chars)
        results = []
        for i, sec in enumerate(parts):
            if progress:
                progress(f"Buchungen {sec.where} ({i + 1}/{len(parts)})")
            system, user = prompts.transactions(sec.text, lang, sec.where)
            results.append(await self._ask(f"Buchungen {sec.where}, Abschnitt {i + 1} von {len(parts)}",
                                           system, user, 0.0, read_transactions))
        return normalize.merge_transactions(results)

    async def run(self, fm: dict, content: str, progress=None, mail: dict | None = None) -> dict:
        """`mail` (PROJ-124): subject/sender/date of the oldest parent mail, a hint for the LLM."""
        def step(text):
            if progress:
                progress(text)

        manual = [m for m in fm.get("manual") or [] if isinstance(m, str)]
        extraction = fm.get("extraction") if isinstance(fm.get("extraction"), dict) else {}
        if extraction.get("empty") is True and "content" not in manual:
            # empty document: no LLM, title stays the original name (AK-32)
            return {"type": "Document", "classification": {"confidence": None, "uncertain": False},
                    "summary": "", "summary_language_uncertain": False,
                    "fields": normalize.normalize_fields("Document", {})}

        lang = fm.get("language") if isinstance(fm.get("language"), str) else None
        head = content[:self.s.head_chars]  # AK-25
        out: dict = {}
        if "type" in manual:  # hand type wins, no classification call (AK-33/34)
            doc_type = fm.get("type")
            if doc_type not in TYPES:
                raise PermanentError(f"Von Hand gesetzter Typ {doc_type!r} ist kein bekannter Dokumenttyp "
                                     f"({', '.join(TYPES)})")
        else:
            step("Klassifizierung")
            doc_type, conf, uncertain = await self.classify(head, lang, mail)
            out["type"] = doc_type
            out["classification"] = {"confidence": round(conf, 3), "uncertain": uncertain}

        step("Felder")
        data, lang_uncertain = await self.extract(doc_type, head, lang, mail)
        fields = normalize.normalize_fields(doc_type, data["fields"])
        if doc_type == "BankStatement":
            fields["transactions"] = await self.transactions(content, lang, progress)
            fields.update(normalize.balance_check(fields))
        out["title"] = normalize.build_title(data["title"], original_name(fm), fm.get("modified"),
                                             fm.get("captured"), self.s.timezone)
        out["summary"] = data["summary"]
        out["summary_language_uncertain"] = lang_uncertain
        out["fields"] = fields
        return out
