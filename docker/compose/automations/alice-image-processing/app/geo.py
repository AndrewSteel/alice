"""Place of an image: takeover from the old Weaviate collection `Image` (read only) or reverse
geocoding at Geoapify (German names), with a rate limit (sliding window of one second)."""
from __future__ import annotations

import asyncio
import re
import time
from collections import deque

import httpx

from .errors import TransientError

LOCATION_KEYS = ("country", "country_code", "city", "district")
_HEX = re.compile(r"^[0-9a-f]{64}$")


class WeaviateUnavailable(Exception):
    """Old Weaviate not reachable or answers with an error: wait, no Geoapify, no failed attempt (AK-12)."""


def _clean(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def location(country=None, country_code=None, city=None, district=None) -> dict:
    code = _clean(country_code)
    return {"country": _clean(country), "country_code": code.upper() if code else None, "city": _clean(city),
            "district": _clean(district)}


def filled(loc: dict | None) -> bool:
    """A place counts as filled with a country or a city (EC-5)."""
    return isinstance(loc, dict) and bool(loc.get("country") or loc.get("city"))


def old_hash(register_hash: str) -> str | None:
    """`sha256:<hex>` of the register → plain hex as stored by the old system; None if not sha256."""
    value = (register_hash or "").strip().lower()
    value = value[len("sha256:"):] if value.startswith("sha256:") else value
    return value if _HEX.match(value) else None


class OldWeaviate:
    """Read-only GraphQL lookup in the old collection `Image` (AK-10, AK-40)."""

    def __init__(self, base_url: str, timeout: float, client: httpx.AsyncClient | None = None):
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self.calls = 0

    async def close(self) -> None:
        await self.http.aclose()

    async def lookup(self, register_hash: str) -> dict | None:
        """Place of the first old object with this hash and a filled place (EC-6), else None."""
        h = old_hash(register_hash)
        if h is None:
            return None
        query = ('{ Get { Image(where: {path: ["file_hash"], operator: Equal, valueText: "%s"}, limit: 20) '
                 '{ country country_code city district } } }' % h)
        self.calls += 1
        try:
            r = await self.http.post("/v1/graphql", json={"query": query})
        except httpx.HTTPError as exc:
            raise WeaviateUnavailable(f"Weaviate nicht erreichbar ({exc.__class__.__name__})") from exc
        if r.status_code != 200:
            raise WeaviateUnavailable(f"Weaviate antwortet {r.status_code}")
        try:
            data = r.json()
        except ValueError:
            raise WeaviateUnavailable("Weaviate-Antwort ist kein JSON") from None
        if data.get("errors"):
            msg = str((data["errors"][0] or {}).get("message", ""))[:200] if isinstance(data["errors"], list) else ""
            raise WeaviateUnavailable(f"Weaviate meldet einen Fehler: {msg}")
        objects = ((data.get("data") or {}).get("Get") or {}).get("Image") or []
        for obj in objects:
            loc = location(**{k: obj.get(k) for k in LOCATION_KEYS})
            if filled(loc):
                return loc
        return None


class RateLimiter:
    """At most `rate` calls in any window of one second (AK-15)."""

    def __init__(self, rate: float, clock=time.monotonic, sleep=asyncio.sleep):
        self.n = max(1, int(rate))
        self.window = 1.0 if rate >= 1 else 1.0 / rate
        self.stamps: deque[float] = deque()
        self.clock, self.sleep = clock, sleep
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            while len(self.stamps) >= self.n:
                wait = self.stamps[0] + self.window + 0.005 - self.clock()
                if wait <= 0:
                    self.stamps.popleft()
                    continue
                await self.sleep(wait)
            self.stamps.append(self.clock())


class Geoapify:
    def __init__(self, base_url: str, key: str, timeout: float, rate: float, client: httpx.AsyncClient | None = None):
        self.key = key
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self.limiter = RateLimiter(rate)
        self.calls = 0

    async def close(self) -> None:
        await self.http.aclose()

    async def reverse(self, lat: float, lon: float) -> dict:
        """German place names (AK-11). No result / missing parts → empty fields (EC-4). Errors → TransientError."""
        await self.limiter.wait()
        self.calls += 1
        params = {"lat": f"{lat:.7f}", "lon": f"{lon:.7f}", "lang": "de", "format": "json", "apiKey": self.key}
        try:
            r = await self.http.get("/v1/geocode/reverse", params=params)
        except httpx.HTTPError as exc:
            raise TransientError(f"Geoapify nicht erreichbar ({exc.__class__.__name__})") from None
        if r.status_code != 200:
            raise TransientError(f"Geoapify antwortet {r.status_code}")
        try:
            results = r.json().get("results") or []
        except (ValueError, AttributeError):
            raise TransientError("Geoapify-Antwort ist kein JSON") from None
        if not results or not isinstance(results[0], dict):
            return location()
        res = results[0]
        return location(res.get("country"), res.get("country_code"), res.get("city"),
                        res.get("suburb") or res.get("district") or res.get("quarter"))
