"""
Shared fixtures and test files.

- Originals are generated in pytest's tmp_path (the "NAS": <tmp>/nas/<share>/...).
- OCR and LibreOffice are replaced by fakes (the real programs run in the container
  smoke test); the fake OCR counts its calls per page.
- FakeRegistry is an in-memory stand-in for the interface of alice-source-registry.
  End-to-end tests against the real register code use TEST_POSTGRES_DSN (test_e2e.py).
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.config import Settings
from app.errors import TransientError
from app.extractor import Extractor


class FakeOcr:
    def __init__(self, text="Gescannter Text der Seite {n} mit Rech-\nnung und Umlauten äöü", delay=0.0,
                 fail_on: int | None = None):
        self.text = text
        self.delay = delay
        self.fail_on = fail_on
        self.calls: list[int] = []

    def __call__(self, png: bytes, page: int) -> str:
        assert png.startswith(b"\x89PNG")
        self.calls.append(page)
        if self.fail_on == page:
            raise TransientError(f"Zeitüberschreitung bei der OCR von Seite {page} (Grenze 1 s je Seite)")
        if self.delay:
            import time

            time.sleep(self.delay)
        return self.text.format(n=page)


# ---------------------------------------------------------------- PDFs
def make_pdf(path, pages, password: str | None = None) -> str:
    """pages: list of "text" strings, None (empty page) or ("scan",) (image only) or ("both", text)."""
    import pymupdf

    doc = pymupdf.open()
    for p in pages:
        page = doc.new_page()
        if isinstance(p, tuple):
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 60), False)
            pix.clear_with(180)
            page.insert_image(pymupdf.Rect(50, 300, 300, 550), stream=pix.tobytes("png"))
            if p[0] == "both":
                page.insert_textbox(pymupdf.Rect(50, 50, 550, 280), p[1], fontsize=10)
        elif p:
            rect = pymupdf.Rect(36, 36, 576, 806)
            # long texts: small font so everything fits on the page
            size = 10 if len(p) < 3000 else 4
            rc = page.insert_textbox(rect, p, fontsize=size)
            assert rc >= 0, "text does not fit on the page"
    kw = {}
    if password:
        kw = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": password, "owner_pw": password + "x"}
    doc.save(str(path), **kw)
    doc.close()
    return str(path)


# ---------------------------------------------------------------- fake register
class FakeRegistry:
    def __init__(self):
        self.sources: dict[str, dict] = {}
        self.queue: list[str] = []
        self.calls: list[tuple] = []
        self.written: dict[str, dict] = {}
        self.state: dict[str, str] = {}
        self.unavailable = False
        self.running = 0
        self.max_running = 0
        self.claim_kinds = []

    def add(self, sid, paths, title="doc"):
        self.sources[sid] = {"id": sid, "kind": "document", "title": title,
                             "locations": [{"path": p, "present": True} for p in paths]}
        self.queue.append(sid)
        self.state[sid] = "pending"

    def _check(self):
        if self.unavailable:
            from app.registry import RegistryUnavailable

            raise RegistryUnavailable("Register nicht erreichbar: ConnectError")

    async def claim(self, limit):
        self._check()
        self.claim_kinds.append(["document"])
        items = []
        while self.queue and len(items) < limit:
            sid = self.queue.pop(0)
            self.state[sid] = "running"
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            items.append({"source_id": sid, "token": str(uuid.uuid4()), "kind": "document",
                          "title": self.sources[sid]["title"]})
        self.calls.append(("claim", limit, len(items)))
        return {"paused": False, "reason": None, "items": items}

    async def get_source(self, sid):
        self._check()
        return self.sources[sid]

    async def write(self, sid, *, fields, content, batch):
        self._check()
        self.calls.append(("write", sid, batch))
        self.written[sid] = {"fields": fields, "content": content, "batch": batch}
        return {"changed": True}

    def _end(self, sid, state):
        self.state[sid] = state
        self.running -= 1

    async def done(self, sid, token):
        self.calls.append(("done", sid))
        self._end(sid, "done")

    async def fail(self, sid, token, error, permanent=False):
        self.calls.append(("fail", sid, error, permanent))
        self._end(sid, "failed_permanent" if permanent else "failed")

    async def release(self, sid, token, delay_seconds=0):
        self.calls.append(("release", sid, delay_seconds))
        self._end(sid, "pending")

    async def heartbeat(self, sid, token):
        self.calls.append(("heartbeat", sid))
        return {"state": "running"}


@pytest.fixture
def nas(tmp_path):
    root = tmp_path / "nas"
    (root / "share").mkdir(parents=True)
    (root / "share" / ".keep").write_text("x")  # a mounted share is never empty
    return root


@pytest.fixture
def settings(nas):
    return Settings(nas_root=str(nas), poll_seconds=0.01, heartbeat_seconds=3600, registry_grace_seconds=0,
                    language_min_chars=40, nas_retry_seconds=60)


@pytest.fixture
def ocr():
    return FakeOcr()


@pytest.fixture
def extractor(settings, ocr):
    return Extractor(settings, ocr=ocr)


@pytest.fixture
def registry():
    return FakeRegistry()


async def drain(worker, rounds=200):
    """Run work-loop steps until the register queue is empty and nothing is active."""
    for _ in range(rounds):
        await worker.step()
        await asyncio.sleep(0)
        if not worker.registry.queue and not worker.active:
            return
    await worker.wait_idle()


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as f:
        f.write(data)
    return str(path)
