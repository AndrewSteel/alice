"""Client for the internal interface of alice-source-registry (PROJ-115)."""
from __future__ import annotations

import json
from decimal import Decimal

import httpx

STAGE = "database"


class RegistryUnavailable(Exception):
    """Register (or its repo) not reachable: nothing counts as a failed attempt."""


class RegistryConflict(Exception):
    """409: markdown locked by an invalid hand edit or missing, or the claim is no longer ours."""


class RegistryError(Exception):
    pass


class RegistryClient:
    def __init__(self, base_url: str, timeout: float = 120, client: httpx.AsyncClient | None = None):
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, path: str, *, json_body=None):
        try:
            r = await self.http.request(method, path, json=json_body)
        except httpx.TransportError as exc:
            raise RegistryUnavailable(f"Register nicht erreichbar: {exc.__class__.__name__}") from exc
        if r.status_code in (502, 503, 504):
            raise RegistryUnavailable(f"Register antwortet {r.status_code}: {r.text[:300]}")
        if r.status_code == 409:
            raise RegistryConflict(r.text[:500])
        if r.status_code >= 400:
            raise RegistryError(f"{method} {path}: {r.status_code} {r.text[:500]}")
        # numbers with a fraction as Decimal: exact amounts, no float rounding (AK-8, EC-7)
        return json.loads(r.text, parse_float=Decimal)

    async def claim(self, limit: int) -> dict:
        """Due database work: only documents (AK-3) whose classification is done (AK-2); deleted
        sources come along (flag `deleted`) so their rows can be removed (AK-20)."""
        return await self._call("POST", f"/stages/{STAGE}/claim",
                                json_body={"limit": limit, "kinds": ["document"], "requires": ["classify"],
                                           "include_deleted": True})

    async def read_document(self, source_id: str) -> dict:
        return await self._call("GET", f"/sources/{source_id}/document")

    def _stage(self, source_id: str, action: str) -> str:
        return f"/sources/{source_id}/stages/{STAGE}/{action}"

    async def done(self, source_id: str, token: str) -> dict:
        return await self._call("POST", self._stage(source_id, "done"), json_body={"token": token})

    async def fail(self, source_id: str, token: str, error: str) -> dict:
        return await self._call("POST", self._stage(source_id, "fail"), json_body={"token": token, "error": error})

    async def release(self, source_id: str, token: str, delay_seconds: int = 0) -> dict:
        return await self._call("POST", self._stage(source_id, "release"),
                                json_body={"token": token, "delay_seconds": delay_seconds})

    async def heartbeat(self, source_id: str, token: str) -> dict:
        return await self._call("POST", self._stage(source_id, "heartbeat"), json_body={"token": token})
