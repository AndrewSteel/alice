"""Heuristic without LLM: is a title/summary mostly not German? (spec "Deutsche Sprache", AK-24)

Counts English against German function words. Short texts (fewer than MIN_WORDS words, e.g. names
and numbers) are never suspicious, and single English technical terms do not count because they are
not function words.
"""
from __future__ import annotations

import re

MIN_WORDS = 6
ENGLISH = frozenset("""
the a and of to is are were be been being for with this that these those from by on at as or
it its has have had which who whom whose not no your our their his her they we you he she what when
where there here than then into about after before over under between can could should would
may might must shall do does did done any each such only very more most other some all both
""".split())
GERMAN = frozenset("""
der die das und ist sind war waren wird werden wurde wurden für mit von den dem des ein eine einer
eines einem einen nicht auf zu im bei sich über auch als oder aus nach zum zur vom wie dass sowie
diese dieser dieses durch bis wenn noch nur mehr kein keine ihr ihre sein seine hat haben unter
""".split())
_WORD = re.compile(r"[a-zäöüß]+")


def not_german(text: str | None, threshold: float) -> bool:
    words = _WORD.findall((text or "").lower())
    if len(words) < MIN_WORDS:
        return False
    en = sum(w in ENGLISH for w in words)
    de = sum(w in GERMAN for w in words)
    return en > de and en / len(words) >= threshold


def suspicious(title: str | None, summary: str | None, threshold: float) -> bool:
    return not_german(summary, threshold) or not_german(title, threshold)
