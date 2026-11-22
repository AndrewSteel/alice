"""PDF: text layer per page; pages without a usable text layer are read by OCR one at a time."""
from __future__ import annotations

import logging
import os
from typing import Callable

from ..errors import PermanentError
from ..text import Result, Section, clean_ocr_text, text_layer_usable, text_quality, tidy

logger = logging.getLogger("alice-text-extraction.pdf")

# ocr(png_bytes, page_number) -> text
OcrFn = Callable[[bytes, int], str]
Progress = Callable[[str], None]


def _check_complete(path: str) -> None:
    """A PDF ends with %%EOF (maybe followed by a few bytes). Without it the file was cut off:
    the library could repair parts, but the content would silently be incomplete (AK-22)."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(1024)
        f.seek(max(0, size - 2048))
        tail = f.read()
    if b"%PDF" not in head:
        raise PermanentError("Datei ist kein PDF (Inhalt passt nicht zur Endung .pdf)")
    if b"%%EOF" not in tail:
        raise PermanentError("PDF ist unvollständig (abgeschnitten) und kann nicht gelesen werden")


def _blank(page) -> bool:
    """No images and no vector drawings: OCR could only read what the text layer already has."""
    try:
        return not page.get_images(full=False) and not page.get_drawings()
    except Exception:
        return False


def extract_pdf(path: str, *, ocr: OcrFn, dpi: int, min_chars: int, min_quality: float,
                progress: Progress | None = None) -> Result:
    import pymupdf

    _check_complete(path)
    try:
        doc = pymupdf.open(path, filetype="pdf")
    except Exception as exc:
        raise PermanentError(f"PDF ist beschädigt und kann nicht geöffnet werden ({exc.__class__.__name__})") from None
    try:
        if doc.needs_pass:
            raise PermanentError("PDF ist passwortgeschützt")
        total = doc.page_count
        result = Result()
        text_pages: list[int] = []
        ocr_tried = False
        for i in range(total):
            n = i + 1
            if progress:
                progress(f"Seite {n}/{total}")
            try:
                page = doc.load_page(i)
                text = tidy(page.get_text("text", sort=False))
            except Exception as exc:
                raise PermanentError(f"PDF ist beschädigt: Seite {n} nicht lesbar ({exc.__class__.__name__})") from None
            if text_layer_usable(text, min_chars, min_quality):
                text_pages.append(n)
            elif _blank(page) and text_quality(text) >= min_quality:
                # empty or just a short readable text (page number): nothing more for OCR to find
                if text.strip():
                    text_pages.append(n)
            else:
                # no usable text layer: render exactly this page and read it by OCR (AK-7, EC-1)
                ocr_tried = True
                png = page.get_pixmap(dpi=dpi).tobytes("png")
                text = clean_ocr_text(ocr(png, n))
                if text.strip():
                    result.ocr_pages.append(n)
            # empty pages get no section, the numbers of the others stay (AK-16)
            result.sections.append(Section(f"Seite {n}" if total > 1 else None, text))
        if result.ocr_pages and text_pages:
            result.method = "mixed"
        elif result.ocr_pages or (ocr_tried and not text_pages):
            result.method = "ocr"
        return result
    finally:
        doc.close()
