"""Client for the internal interface of alice-source-registry (PROJ-115)."""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

logger = logging.getLogger("alice-file-detection.registry")


class RegistryUnavailable(Exception):
    """Register or its repo not reachable: the run pauses and is repeated later (AK-25)."""


class RegistryError(Exception):
    """The register rejected a call for one file."""


class RegistryClient:
    def __init__(self, base_url: str, timeout: float = 120, client: httpx.AsyncClient | None = None):
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, path: str, *, json=None, params=None, ok404: bool = False):
        try:
            r = await self.http.request(method, path, json=json, params=params)
        except httpx.TransportError as exc:
            raise RegistryUnavailable(f"Register nicht erreichbar: {exc.__class__.__name__}: {exc}") from exc
        if r.status_code in (502, 503, 504):
            raise RegistryUnavailable(f"Register antwortet {r.status_code}: {r.text[:300]}")
        if r.status_code == 404 and ok404:
            return None
        if r.status_code >= 400:
            raise RegistryError(f"{method} {path}: {r.status_code} {r.text[:500]}")
        return r.json()

    async def health(self) -> bool:
        try:
            r = await self.http.get("/health")
            return r.status_code == 200
        except httpx.TransportError:
            return False

    async def register(self, *, kind: str, hash: str, title: str, path: str, size: int, modified: datetime,
                       batch: bool = False) -> dict:
        return await self._call("POST", "/sources", json={
            "kind": kind, "hash": hash, "title": title, "location": {"path": path}, "size": size,
            "modified": modified.isoformat(), "stage": "detect", "complete": True, "batch": batch})

    async def by_hash(self, hash: str) -> dict | None:
        return await self._call("GET", "/sources", params={"hash": hash}, ok404=True)

    async def get_source(self, source_id: str) -> dict | None:
        return await self._call("GET", f"/sources/{source_id}", ok404=True)

    async def gone(self, source_id: str, path: str) -> dict | None:
        """Location disappeared; None if the register does not know it (any more)."""
        return await self._call("POST", f"/sources/{source_id}/locations/gone", json={"path": path}, ok404=True)

    async def update_original(self, source_id: str, *, hash: str, size: int, modified: datetime) -> dict:
        return await self._call("PUT", f"/sources/{source_id}/original", json={
            "hash": hash, "size": size, "modified": modified.isoformat(), "stage": "detect"})

    async def flush(self) -> None:
        await self._call("POST", "/maintenance/flush")
