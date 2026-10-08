"""
Text rules for the lists agent (PROJ-106). Pure — no I/O.

- split_items(): the deterministic multi-entry rule. Every comma and every
  "und" separates entries, without exception ("Salz und Pfeffer" → two).
  Quantities stay with their entry. The LLM only hands over the raw phrase.
- Name / title matching for lists and entries (approximate names such as
  "Baumarktliste" → "Baumarkt").
"""
from __future__ import annotations

import difflib
import re

MAX_ITEMS_PER_CALL = 30

# "and" is the same rule for users with English as their language.
_SPLIT_RE = re.compile(r"\s*,\s*|\s+und\s+|\s+and\s+", re.IGNORECASE)
_EDGE_RE = re.compile(r"^[\s\"'„“”‚‘’.!?:-]+|[\s\"'„“”‚‘’.!?:-]+$")
# A leading/trailing "und" left over by the model ("und Eier").
_DANGLING_RE = re.compile(r"^(?:und|and)\s+|\s+(?:und|and)$", re.IGNORECASE)


def clean(text: str) -> str:
    text = _EDGE_RE.sub("", text or "")
    text = _DANGLING_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def split_items(raw) -> list[str]:
    """'Milch, Butter und Eier' → ['Milch', 'Butter', 'Eier'].

    A list from the model is joined first, so the rule applies the same way
    no matter how the model packaged the phrase.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        raw = ", ".join(str(x) for x in raw if x is not None)
    parts = [clean(p) for p in _SPLIT_RE.split(str(raw))]
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def norm(s: str) -> str:
    s = (s or "").lower().replace("ß", "ss")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_LIST_FILLER = {"die", "der", "den", "das", "meine", "meiner", "meinen", "mein", "unsere", "unserer",
                "unseren", "unser", "liste", "list", "the", "my", "our", "gemeinsame", "gemeinsamen",
                "private", "privaten"}
_SHOPPING_RE = re.compile(r"^(?:die\s+|der\s+|den\s+|meine[nr]?\s+|unsere[nr]?\s+|the\s+|my\s+|our\s+)?"
                          r"(einkaufs(?:liste|zettel)|einkauf|shopping(?:\s*list)?|grocery\s*list)$",
                          re.IGNORECASE)


def is_shopping_alias(name: str) -> bool:
    """'Einkaufsliste' / 'Einkaufszettel' always mean the flagged shopping list."""
    return bool(_SHOPPING_RE.match((name or "").strip()))


def list_core(name: str) -> str:
    """'die Baumarktliste' → 'baumarkt'; 'Liste Urlaub' → 'urlaub'."""
    toks = [t for t in norm(name).split() if t not in _LIST_FILLER]
    core = " ".join(toks)
    for suffix in ("liste", "list"):
        if core.endswith(suffix) and len(core) - len(suffix) >= 3:
            core = core[: -len(suffix)].rstrip(" -")
            break
    return core


def name_key(name: str) -> str:
    """Uniqueness key — mirrors the DB index lower(btrim(name))."""
    return (name or "").strip().lower()


def match_names(query: str, names: list[str]) -> list[int]:
    """Indices of names that match `query`: exact (normalised) first, else
    approximate (containment or high similarity of the cores)."""
    q = list_core(query)
    if not q:
        return []
    cores = [list_core(n) for n in names]
    exact = [i for i, c in enumerate(cores) if c == q]
    if exact:
        return exact
    out = []
    for i, c in enumerate(cores):
        if not c:
            continue
        if (len(q) >= 3 and q in c) or (len(c) >= 3 and c in q) or \
                difflib.SequenceMatcher(None, q, c).ratio() >= 0.8:
            out.append(i)
    return out


_TITLE_STOP = {"der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "aufgabe", "eintrag",
               "the", "a", "an", "task", "item"}


def _title_tokens(s: str) -> list[str]:
    return [t for t in norm(s).split() if t not in _TITLE_STOP]


def title_score(query: str, title: str) -> int:
    """0 = no match, 3 = same title, 2 = all query words in the title,
    1 = fuzzy similarity (Whisper variants)."""
    q, t = _title_tokens(query), _title_tokens(title)
    if not q:
        return 0
    if q == t:
        return 3
    qs, ts = " ".join(q), " ".join(t)
    if all(any(w == x or (len(w) >= 4 and x.startswith(w)) for x in t) for w in q):
        return 2
    if difflib.SequenceMatcher(None, qs, ts).ratio() >= 0.82:
        return 1
    return 0


def same_title(a: str, b: str) -> bool:
    return norm(a) == norm(b)
