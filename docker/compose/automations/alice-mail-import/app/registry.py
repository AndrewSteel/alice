"""Client for the internal interface of alice-source-registry (PROJ-115). Sources, locations, stage
states and markdowns of mails are changed only through the register."""
from __future__ import annotations

from datetime import datetime

import httpx


class RegistryUnavailable(Exception):
    """Register (or its repo) not reachable: nothing changes, the work pauses."""


class RegistryConflict(Exception):
    """409: markdown locked/missing or the claim is no longer ours."""


class RegistryNotFound(Exception):
    pass


class RegistryError(Exception):
    pass


class RegistryClient:
    def __init__(self, base_url: str, timeout: float = 120, client: httpx.AsyncClient | None = None):
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, path: str, *, json=None, params=None):
        try:
            r = await self.http.request(method, path, json=json, params=params)
        except httpx.TransportError as exc:
            raise RegistryUnavailable(f"Register nicht erreichbar: {exc.__class__.__name__}") from exc
        if r.status_code in (502, 503, 504):
            raise RegistryUnavailable(f"Register antwortet {r.status_code}: {r.text[:300]}")
        if r.status_code == 404:
            raise RegistryNotFound(r.text[:300])
        if r.status_code == 409:
            raise RegistryConflict(r.text[:500])
        if r.status_code >= 400:
            raise RegistryError(f"{method} {path}: {r.status_code} {r.text[:500]}")
        return r.json()

    async def available(self) -> tuple[bool, str]:
        try:
            r = await self.http.get("/health")
        except httpx.TransportError as exc:
            return False, f"Register nicht erreichbar: {exc.__class__.__name__}"
        if r.status_code == 200:
            return True, ""
        try:
            reasons = r.json().get("reasons") or []
        except ValueError:
            reasons = []
        return False, "Register/Repo nicht verfügbar: " + ("; ".join(reasons) or f"HTTP {r.status_code}")

    # ---------------------------------------------------------------- sources
    async def find_by_hash(self, h: str) -> dict | None:
        try:
            return await self._call("GET", "/sources", params={"hash": h})
        except RegistryNotFound:
            return None

    async def get_source(self, source_id: str) -> dict:
        return await self._call("GET", f"/sources/{source_id}")

    async def register(self, *, hash: str, title: str, location: dict, size: int, captured: datetime,
                       batch: bool) -> dict:
        return await self._call("POST", "/sources", json={
            "kind": "email", "hash": hash, "title": title, "location": location, "size": size,
            "captured": captured.isoformat(), "stage": "detect", "complete": True, "batch": batch})

    async def register_attachment(self, *, kind: str, hash: str, title: str, path: str, size: int,
                                  modified: datetime | None, captured: datetime, parent: str, batch: bool) -> dict:
        """PROJ-124: a mail attachment as source (known hash: further location + parent)."""
        body = {"kind": kind, "hash": hash, "title": title, "location": {"path": path}, "size": size,
                "captured": captured.isoformat(), "parents": [parent], "stage": "detect", "complete": True,
                "batch": batch}
        if modified is not None:
            body["modified"] = modified.isoformat()
        return await self._call("POST", "/sources", json=body)

    async def write_links(self, source_id: str, *, fields: dict, content: str | None, batch: bool) -> dict:
        """PROJ-124: attachment ids + links in the mail markdown, own commit, classify of the mail stays."""
        body = {"stage": "extract", "label": "attachments", "keep_stages": ["classify"], "fields": fields,
                "batch": batch}
        if content is not None:
            body["content"] = content
        return await self._call("PUT", f"/sources/{source_id}/document", json=body)

    async def flush(self) -> dict:
        return await self._call("POST", "/maintenance/flush")

    async def event(self, source_id: str, level: str, event: str, message: str) -> dict:
        return await self._call("POST", f"/sources/{source_id}/events",
                                json={"level": level, "event": event, "message": message[:4000]})

    async def add_location(self, source_id: str, location: dict) -> dict:
        return await self._call("POST", f"/sources/{source_id}/locations", json=location)

    async def remove_location(self, source_id: str, location: dict) -> dict:
        return await self._call("POST", f"/sources/{source_id}/locations/gone", json=location)

    # ---------------------------------------------------------------- stages
    async def claim(self, stage: str, limit: int, requires: list[str] | None = None) -> dict:
        body = {"limit": limit, "kinds": ["email"]}
        if requires:
            body["requires"] = requires
        return await self._call("POST", f"/stages/{stage}/claim", json=body)

    async def read_document(self, source_id: str) -> dict:
        return await self._call("GET", f"/sources/{source_id}/document")

    async def write(self, source_id: str, *, stage: str, fields: dict, content: str | None, token: str,
                    batch: bool) -> dict:
        body = {"stage": stage, "fields": fields, "batch": batch, "token": token}
        if content is not None:
            body["content"] = content
        return await self._call("PUT", f"/sources/{source_id}/document", json=body)

    def _stage(self, source_id: str, stage: str, action: str) -> str:
        return f"/sources/{source_id}/stages/{stage}/{action}"

    async def done(self, source_id: str, stage: str, token: str) -> dict:
        return await self._call("POST", self._stage(source_id, stage, "done"), json={"token": token})

    async def fail(self, source_id: str, stage: str, token: str, error: str, permanent: bool = False) -> dict:
        return await self._call("POST", self._stage(source_id, stage, "fail"),
                                json={"token": token, "error": error[:4000], "permanent": permanent})

    async def release(self, source_id: str, stage: str, token: str, delay_seconds: int = 0) -> dict:
        return await self._call("POST", self._stage(source_id, stage, "release"),
                                json={"token": token, "delay_seconds": delay_seconds})

    async def heartbeat(self, source_id: str, stage: str, token: str) -> dict:
        return await self._call("POST", self._stage(source_id, stage, "heartbeat"), json={"token": token})
