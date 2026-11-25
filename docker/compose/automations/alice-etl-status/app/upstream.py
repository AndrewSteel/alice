"""Clients for the internal interfaces of alice-source-registry (PROJ-115) and
alice-etl-rebuild (PROJ-120). Both are only reachable inside the Docker network."""
from __future__ import annotations

import httpx


class Unavailable(Exception):
    """Service not reachable (or answering 5xx)."""

    def __init__(self, service: str, message: str):
        super().__init__(message)
        self.service = service


class Rejected(Exception):
    """The service rejected the call (4xx): passed on with its status and reason."""

    def __init__(self, status: int, body: dict):
        super().__init__(body.get("detail") or body.get("error") or str(status))
        self.status = status
        self.body = body


class Client:
    def __init__(self, service: str, base_url: str, timeout: float, client: httpx.AsyncClient | None = None):
        self.service = service
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self.http.aclose()

    async def call(self, method: str, path: str, *, json=None, params=None, timeout=None, ok_5xx=False):
        kw = {}
        if json is not None:
            kw["json"] = json
        if params:
            kw["params"] = {k: v for k, v in params.items() if v is not None}
        if timeout is not None:
            kw["timeout"] = timeout
        try:
            r = await self.http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise Unavailable(self.service, f"{self.service} nicht erreichbar: {exc.__class__.__name__}") from exc
        try:
            body = r.json()
        except ValueError:
            body = {"detail": r.text[:500]}
        if r.status_code >= 500 and not (ok_5xx and isinstance(body, dict) and "status" in body):
            raise Unavailable(self.service, f"{self.service} antwortet {r.status_code}")
        if 400 <= r.status_code < 500:
            if not isinstance(body, dict):
                body = {"detail": str(body)[:500]}
            if isinstance(body.get("detail"), list):  # FastAPI validation errors
                body = {"error": "invalid", "detail": "; ".join(str(e.get("msg", e)) for e in body["detail"])}
            raise Rejected(r.status_code, body)
        return body
