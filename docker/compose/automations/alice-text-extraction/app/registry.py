"""Client for the internal interface of alice-source-registry (PROJ-115)."""
from __future__ import annotations

import httpx

STAGE = "extract"


class RegistryUnavailable(Exception):
    """Register (or its repo) not reachable: nothing counts as a failed attempt."""


class RegistryConflict(Exception):
    """409: markdown locked by an invalid hand edit, or the claim is no longer ours."""


class RegistryError(Exception):
    pass


class RegistryClient:
    def __init__(self, base_url: str, timeout: float = 120, client: httpx.AsyncClient | None = None):
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, path: str, *, json=None):
        try:
            r = await self.http.request(method, path, json=json)
        except httpx.TransportError as exc:
            raise RegistryUnavailable(f"Register nicht erreichbar: {exc.__class__.__name__}") from exc
        if r.status_code in (502, 503, 504):
            raise RegistryUnavailable(f"Register antwortet {r.status_code}: {r.text[:300]}")
        if r.status_code == 409:
            raise RegistryConflict(r.text[:500])
        if r.status_code >= 400:
            raise RegistryError(f"{method} {path}: {r.status_code} {r.text[:500]}")
        return r.json()

    async def claim(self, limit: int) -> dict:
        """Due work of the extract stage, only sources of kind document (AK-3)."""
        return await self._call("POST", f"/stages/{STAGE}/claim", json={"limit": limit, "kinds": ["document"]})

    async def get_source(self, source_id: str) -> dict:
        return await self._call("GET", f"/sources/{source_id}")

    async def write(self, source_id: str, *, fields: dict, content: str, batch: bool) -> dict:
        return await self._call("PUT", f"/sources/{source_id}/document",
                                json={"stage": STAGE, "fields": fields, "content": content, "batch": batch})

    def _stage(self, source_id: str, action: str) -> str:
        return f"/sources/{source_id}/stages/{STAGE}/{action}"

    async def done(self, source_id: str, token: str) -> dict:
        return await self._call("POST", self._stage(source_id, "done"), json={"token": token})

    async def fail(self, source_id: str, token: str, error: str, permanent: bool = False) -> dict:
        return await self._call("POST", self._stage(source_id, "fail"),
                                json={"token": token, "error": error, "permanent": permanent})

    async def release(self, source_id: str, token: str, delay_seconds: int = 0) -> dict:
        return await self._call("POST", self._stage(source_id, "release"),
                                json={"token": token, "delay_seconds": delay_seconds})

    async def heartbeat(self, source_id: str, token: str) -> dict:
        return await self._call("POST", self._stage(source_id, "heartbeat"), json={"token": token})
