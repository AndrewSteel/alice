"""One original → Result. Chooses the reader by file extension; blocking, runs in a worker thread."""
from __future__ import annotations

import os
from typing import Callable

from .config import Settings
from .errors import PermanentError, TransientError
from .formats import office, pdf, plain
from .text import Result

SUPPORTED = ("pdf", "txt", "md", "csv", *office.TEXT_EXTS, *office.SHEET_EXTS, *office.SLIDE_EXTS)


def extension(path: str) -> str:
    return os.path.splitext(path)[1].lower().lstrip(".")


class Extractor:
    def __init__(self, settings: Settings, ocr: Callable[[bytes, int], str] | None = None,
                 converter_factory: Callable[[], Callable] | None = None):
        from .ocr import TesseractOcr

        self.s = settings
        self.ocr = ocr or TesseractOcr(settings.ocr_languages, settings.ocr_page_timeout_seconds)
        self.converter_factory = converter_factory or office.LibreOffice

    def check_size(self, path: str) -> None:
        size = os.path.getsize(path)
        limit = self.s.max_file_mb * 1024 * 1024
        if size > limit:
            raise PermanentError(f"Datei zu groß ({size / 1024 / 1024:.0f} MB, Grenze {self.s.max_file_mb:g} MB)")

    def extract(self, path: str, progress: Callable[[str], None] | None = None) -> Result:
        ext = extension(path)
        if ext not in SUPPORTED:
            raise PermanentError(f"Format .{ext or '(ohne Endung)'} wird nicht unterstützt")
        self.check_size(path)
        try:
            if ext == "pdf":
                return pdf.extract_pdf(path, ocr=self.ocr, dpi=self.s.ocr_dpi, min_chars=self.s.text_min_chars,
                                       min_quality=self.s.text_min_quality, progress=progress)
            if ext in ("txt", "md"):
                return plain.extract_text_file(path, ext)
            if ext == "csv":
                return plain.extract_csv(path)
            converter = self.converter_factory()
            try:
                return office.extract_office(path, ext, convert=converter, timeout=self.s.file_timeout_seconds)
            finally:
                cleanup = getattr(converter, "cleanup", None)
                if cleanup:
                    cleanup()
        except MemoryError:
            raise TransientError("Speichermangel bei der Extraktion") from None
