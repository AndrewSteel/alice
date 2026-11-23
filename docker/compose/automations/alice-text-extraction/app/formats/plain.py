"""txt, md (content unchanged) and csv (one Markdown table)."""
from __future__ import annotations

import csv
import io

from ..text import Result, Section, decode_text, md_table, strip_control

DELIMITERS = ";,\t|"


def extract_text_file(path: str, ext: str) -> Result:
    with open(path, "rb") as f:
        text = decode_text(f.read(), ext)
    return Result(sections=[Section(None, strip_control(text).strip("\n"))])


def _delimiter(text: str) -> str:
    sample = text[:65536]
    try:
        return csv.Sniffer().sniff(sample, delimiters=DELIMITERS).delimiter
    except csv.Error:
        lines = [l for l in sample.split("\n")[:50] if l.strip()]
        # the candidate that appears most often, and equally often in every line
        best, score = ",", -1
        for d in DELIMITERS:
            counts = {l.count(d) for l in lines}
            n = min(counts) if counts else 0
            if n > 0 and len(counts) == 1 and n > score:
                best, score = d, n
        if score < 0:
            best = max(DELIMITERS, key=lambda d: sample.count(d))
        return best


def extract_csv(path: str) -> Result:
    with open(path, "rb") as f:
        text = decode_text(f.read(), "csv")
    rows = list(csv.reader(io.StringIO(text), delimiter=_delimiter(text)))
    return Result(sections=[Section(None, md_table(rows))])
