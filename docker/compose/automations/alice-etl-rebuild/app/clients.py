"""Clients for the internal interfaces of alice-source-registry (PROJ-115) and
alice-file-detection (PROJ-116). Stage states and source markdowns are only ever
changed through the register; the NAS only through the detection service."""
from __future__ import annotations

import httpx


class Unavailable(Exception):
    """Service (or the register's repo) not reachable."""


class CallError(Exception):
    """The service rejected the call."""


class Busy(Exception):
    """409 from the detection service: a nightly run is active or the lease is held."""


class _Client:
    name = "Dienst"

    def __init__(self, base_url: str, timeout: float, client: httpx.AsyncClient | None = None):
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, path: str, *, json=None, timeout=None):
        kw = {"json": json} if json is not None else {}
        if timeout is not None:
            kw["timeout"] = timeout
        try:
            r = await self.http.request(method, path, **kw)
        except httpx.TransportError as exc:
            raise Unavailable(f"{self.name} nicht erreichbar: {exc.__class__.__name__}") from exc
        if r.status_code in (502, 503, 504):
            raise Unavailable(f"{self.name} antwortet {r.status_code}: {r.text[:300]}")
        if r.status_code == 409:
            raise Busy(r.text[:300])
        if r.status_code >= 400:
            raise CallError(f"{method} {path}: {r.status_code} {r.text[:500]}")
        return r.json()


class RegistryClient(_Client):
    name = "Register"

    async def health(self) -> tuple[bool, str]:
        """(ok, reason): register reachable and its repo available."""
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

    async def release(self, run_id: int, items: list[dict]) -> dict:
        return await self._call("POST", "/rebuild/release", json={"run": run_id, "items": items})

    async def retry(self, source_id: str, stage: str) -> dict:
        return await self._call("POST", f"/sources/{source_id}/stages/{stage}/retry")

    async def event(self, source_id: str, event: str, message: str, level: str = "info") -> dict:
        return await self._call("POST", f"/sources/{source_id}/events",
                                json={"level": level, "event": event, "message": message})

    async def repo_check(self, timeout: float) -> dict:
        return await self._call("GET", "/maintenance/repo-check", timeout=timeout)

    async def repo_repair(self, items: list[dict], timeout: float) -> dict:
        return await self._call("POST", "/maintenance/repo-repair", json={"items": items}, timeout=timeout)


class DetectionClient(_Client):
    name = "Datei-Erkennung"

    async def lease(self, token: str | None, seconds: int) -> str:
        body = {"seconds": seconds, **({"token": token} if token else {})}
        return (await self._call("POST", "/reconcile/lease", json=body))["token"]

    async def unlease(self, token: str) -> None:
        await self._call("DELETE", f"/reconcile/lease/{token}")

    async def check(self, timeout: float) -> dict:
        return await self._call("POST", "/reconcile/check", timeout=timeout)

    async def register(self, paths: list[str], timeout: float) -> dict:
        return await self._call("POST", "/reconcile/register", json={"items": [{"path": p} for p in paths]},
                                timeout=timeout)

    async def rehash(self, *, full: bool, cycle_days: float, max_seconds: float | None, max_bytes: int | None,
                     timeout: float) -> dict:
        body = {"full": full, "cycle_days": cycle_days}
        if max_seconds:
            body["max_seconds"] = max_seconds
        if max_bytes:
            body["max_bytes"] = max_bytes
        return await self._call("POST", "/reconcile/rehash", json=body, timeout=timeout)

    async def apply(self, paths: list[str], timeout: float) -> dict:
        return await self._call("POST", "/reconcile/apply", json={"paths": paths}, timeout=timeout)
