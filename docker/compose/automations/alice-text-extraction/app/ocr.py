"""OCR of one rendered page with Tesseract, with a time limit per page."""
from __future__ import annotations

import os
import signal
import subprocess

from .errors import TransientError


class TesseractOcr:
    def __init__(self, languages: str = "deu+eng", timeout: float = 120):
        self.languages = languages
        self.timeout = timeout

    def __call__(self, png: bytes, page: int) -> str:
        proc = subprocess.Popen(["tesseract", "stdin", "stdout", "-l", self.languages, "--psm", "3"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
        try:
            out, err = proc.communicate(png, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise TransientError(f"Zeitüberschreitung bei der OCR von Seite {page} "
                                 f"(Grenze {int(self.timeout)} s je Seite)") from None
        if proc.returncode != 0:
            raise TransientError(f"OCR von Seite {page} fehlgeschlagen (Code {proc.returncode}): "
                                 f"{err.decode(errors='replace').strip()[:200]}")
        return out.decode("utf-8", errors="replace")
