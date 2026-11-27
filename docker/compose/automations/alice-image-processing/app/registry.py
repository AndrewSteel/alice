"""Client for the internal interface of alice-source-registry (PROJ-115)."""
from __future__ import annotations

from datetime import datetime

import httpx

DESCRIBE = "extract"  # description of an image incl. EXIF and title (PROJ-125)
LOCATE = "locate"     # place of an image from its GPS coordinates (PROJ-125)


class RegistryUnavailable(Exception):
    """Register (or its repo) not reachable: nothing counts as a failed attempt."""


class RegistryConflict(Exception):
    """409: markdown locked by an invalid hand edit or missing, or the claim is no longer ours."""


class RegistryNotFound(Exception):
    pass


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
        if r.status_code == 404:
            raise RegistryNotFound(r.text[:300])
        if r.status_code >= 400:
            raise RegistryError(f"{method} {path}: {r.status_code} {r.text[:500]}")
        return r.json()

    async def claim(self, stage: str, limit: int, *, since: datetime | None = None,
                    before: datetime | None = None, ids: list[str] | None = None) -> dict:
        """Due work of `stage`, only images (AK-4); deleted sources never come (AK-6)."""
        body: dict = {"limit": limit, "kinds": ["image"]}
        if since is not None:
            body["registered_since"] = since.isoformat()
        if before is not None:
            body["registered_before"] = before.isoformat()
        if ids:
            body["source_ids"] = ids
        return await self._call("POST", f"/stages/{stage}/claim", json=body)

    async def get_source(self, source_id: str) -> dict:
        return await self._call("GET", f"/sources/{source_id}")

    async def read_document(self, source_id: str) -> dict:
        return await self._call("GET", f"/sources/{source_id}/document")

    async def write(self, source_id: str, stage: str, *, token: str, fields: dict, content: str | None = None,
                    batch: bool = False) -> dict:
        """With the claim token: discarded by the register if the stage was taken back meanwhile."""
        body = {"stage": stage, "fields": fields, "batch": batch, "token": token}
        if content is not None:
            body["content"] = content
        return await self._call("PUT", f"/sources/{source_id}/document", json=body)

    def _stage(self, source_id: str, stage: str, action: str) -> str:
        return f"/sources/{source_id}/stages/{stage}/{action}"

    async def done(self, source_id: str, stage: str, token: str, skipped: bool = False) -> dict:
        return await self._call("POST", self._stage(source_id, stage, "done"),
                                json={"token": token, "skipped": skipped})

    async def fail(self, source_id: str, stage: str, token: str, error: str, permanent: bool = False) -> dict:
        return await self._call("POST", self._stage(source_id, stage, "fail"),
                                json={"token": token, "error": error, "permanent": permanent})

    async def release(self, source_id: str, stage: str, token: str, delay_seconds: int = 0) -> dict:
        return await self._call("POST", self._stage(source_id, stage, "release"),
                                json={"token": token, "delay_seconds": max(0, min(86400, int(delay_seconds)))})

    async def heartbeat(self, source_id: str, stage: str, token: str) -> dict:
        return await self._call("POST", self._stage(source_id, stage, "heartbeat"), json={"token": token})

    async def retry(self, source_id: str, stage: str) -> dict:
        return await self._call("POST", self._stage(source_id, stage, "retry"))
