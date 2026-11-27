"""
Shared fixtures.

- make_image(): test images in every format, with or without EXIF (time, GPS, camera, orientation).
- FakeGateway: OpenAI compatible stand-in for alice-llm-gateway (httpx MockTransport); records every
  request (prompt, image sizes, key, enable_thinking) and answers from a script.
- FakeGeoapify / FakeWeaviate: HTTP mocks of Geoapify and the old Weaviate collection `Image`.
- FakeStore: in-memory stand-in for the PostgreSQL state (end-to-end tests use the real one).
"""
from __future__ import annotations

import base64
import io
import json
import time
from datetime import date, datetime, timezone

import httpx
import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational as R

from app.config import Settings
from app.geo import Geoapify, OldWeaviate
from app.vision import VisionClient

KEY = "test-background-key"
LONG_DESCRIPTION = ("Ein breiter Sandstrand bei Sonnenuntergang. Im Vordergrund liegen zwei Liegestühle, "
                    "dahinter spielen drei Kinder am Wasser. Der Himmel leuchtet orange und violett, "
                    "die Stimmung ist ruhig und sommerlich.")


def make_image(path, size=(60, 40), fmt=None, *, taken="2024:07:12 14:03:22", gps=None, camera=("Canon", "EOS R5"),
               orientation=None, exif=True, mode="RGB", frames=1):
    """gps: (lat, lon, alt) signed decimal degrees, written as DMS + N/S/E/W."""
    img = Image.new(mode, size, (200, 120, 40) if mode == "RGB" else 128)
    kw = {}
    if exif:
        e = Image.Exif()
        if camera:
            e[0x010F], e[0x0110] = camera
        if orientation:
            e[0x0112] = orientation
        if taken:
            e.get_ifd(0x8769)[0x9003] = taken
        if gps:
            lat, lon, alt = gps
            g = e.get_ifd(0x8825)

            def dms(v):
                v = abs(v)
                d = int(v)
                m = int((v - d) * 60)
                s = round((v - d - m / 60) * 3600 * 1000)
                return (R(d, 1), R(m, 1), R(s, 1000))
            g[1], g[2] = ("S" if lat < 0 else "N"), dms(lat)
            g[3], g[4] = ("W" if lon < 0 else "E"), dms(lon)
            if alt is not None:
                g[5], g[6] = (1 if alt < 0 else 0), R(round(abs(alt) * 10), 10)
        kw["exif"] = e.tobytes()
    fmt = fmt or {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "heic": "HEIF", "tif": "TIFF",
                  "tiff": "TIFF"}[str(path).rsplit(".", 1)[1].lower()]
    if frames > 1:
        kw["save_all"] = True
        kw["append_images"] = [Image.new(mode, (size[0] * 2, size[1] * 2), (0, 0, 255)) for _ in range(frames - 1)]
    img.save(path, fmt, **kw)
    return str(path)


def jpeg_size(b64: str) -> tuple[int, int]:
    return Image.open(io.BytesIO(base64.b64decode(b64))).size


class FakeGateway:
    def __init__(self, model="qwen3.8-27b"):
        self.requests: list[dict] = []
        self.answers: list = []          # scripted answers (dict, str, exception, or callable)
        self.model = model
        self.default = {"description": LONG_DESCRIPTION, "title": "Strand bei Sonnenuntergang", "text_in_image": ""}
        self.tile_default = {"description": "Ein Ausschnitt mit Strand, Wasser und Himmel.", "text_in_image": ""}
        self.down = False
        self.status = 200
        self.active = 0
        self.max_active = 0
        self.delay = 0.0

    def calls(self) -> list[dict]:
        return self.requests

    async def handler(self, request: httpx.Request) -> httpx.Response:
        import asyncio

        if self.down:
            raise httpx.ConnectError("gateway down", request=request)
        body = json.loads(request.content)
        content = body["messages"][0]["content"]
        if isinstance(content, list):
            prompt = next(c["text"] for c in content if c["type"] == "text")
            images = [c["image_url"]["url"].split(",", 1)[1] for c in content if c["type"] == "image_url"]
        else:
            prompt, images = content, []
        rec = {"prompt": prompt, "images": images, "sizes": [jpeg_size(i) for i in images],
               "auth": request.headers.get("authorization"), "model": body.get("model"),
               "template_kwargs": body.get("chat_template_kwargs"), "at": time.monotonic()}
        self.requests.append(rec)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        finally:
            self.active -= 1
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        tile = prompt.startswith("Dies ist Ausschnitt")
        answer = self.answers.pop(0) if self.answers else (self.tile_default if tile else self.default)
        if callable(answer) and not isinstance(answer, type):
            answer = answer(rec)
        if isinstance(answer, Exception):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        out = {"choices": [{"message": {"role": "assistant", "content": text}}]}
        if self.model:
            out["model"] = self.model
        return httpx.Response(200, json=out)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url="http://alice-llm-gateway:8011", transport=httpx.MockTransport(self.handler))


class FakeGeoapify:
    def __init__(self):
        self.requests: list[dict] = []
        self.status = 200
        self.result = {"country": "Italien", "country_code": "it", "city": "Rimini", "suburb": "Marina Centro"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append({"params": dict(request.url.params), "at": time.monotonic()})
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        return httpx.Response(200, json={"results": [self.result] if self.result else []})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url="https://api.geoapify.test", transport=httpx.MockTransport(self.handler))


class FakeWeaviate:
    """GraphQL stand-in: objects by file_hash (plain hex, like the old system)."""

    def __init__(self):
        self.objects: dict[str, list[dict]] = {}
        self.down = False
        self.queries: list[str] = []
        self.methods: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.methods.append(f"{request.method} {request.url.path}")
        if self.down:
            raise httpx.ConnectError("weaviate down", request=request)
        q = json.loads(request.content)["query"]
        self.queries.append(q)
        h = q.split('valueText: "', 1)[1].split('"', 1)[0]
        return httpx.Response(200, json={"data": {"Get": {"Image": self.objects.get(h, [])}}})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url="http://weaviate:8080", transport=httpx.MockTransport(self.handler))


class FakeStore:
    def __init__(self, first_start: datetime | None = None):
        self.start = first_start or datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
        self.usage: dict[date, int] = {}
        self.requests: list[str] = []
        self.down = False

    def _check(self):
        if self.down:
            raise ConnectionError("postgres down")

    async def first_start(self):
        self._check()
        return self.start

    async def reserve_geocode(self, day, limit):
        self._check()
        if self.usage.get(day, 0) >= limit:
            return False
        self.usage[day] = self.usage.get(day, 0) + 1
        return True

    async def geocode_calls(self, day):
        return self.usage.get(day, 0)

    async def request(self, sid):
        self._check()
        if sid not in self.requests:
            self.requests.append(sid)

    async def requested(self, limit=100):
        self._check()
        return list(self.requests[:limit])

    async def forget(self, ids):
        self.requests = [r for r in self.requests if r not in ids]


@pytest.fixture
def settings(tmp_path):
    return Settings(poll_seconds=0.01, heartbeat_seconds=3600, registry_grace_seconds=0, gateway_key=KEY,
                    model="qwen-vision", llm_retry_seconds=0, nas_root=str(tmp_path / "nas"),
                    nas_retry_seconds=0, weaviate_retry_seconds=300, geoapify_daily_limit=3000, geoapify_rate=1000)


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def geoapify_mock():
    return FakeGeoapify()


@pytest.fixture
def weaviate_mock():
    return FakeWeaviate()


@pytest.fixture
def vision(settings, gateway):
    return VisionClient(settings.gateway_url, settings.gateway_key, settings.model, 5, 1000, client=gateway.client())


@pytest.fixture
def geoapify(settings, geoapify_mock):
    return Geoapify("https://api.geoapify.test", "test-geo-key", 5, settings.geoapify_rate,
                    client=geoapify_mock.client())


@pytest.fixture
def weaviate(weaviate_mock):
    return OldWeaviate("http://weaviate:8080", 5, client=weaviate_mock.client())


@pytest.fixture
def nas(tmp_path):
    """A NAS root with one share that holds the test originals."""
    share = tmp_path / "nas" / "fotos"
    share.mkdir(parents=True)
    (share / ".keep").write_text("x")
    return share
