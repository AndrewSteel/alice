"""Client for alice-llm-gateway (OpenAI compatible /v1/chat/completions, PROJ-111).

The service calls the LLM only through the gateway with its own background key (AK-40).
"""
from __future__ import annotations

import json
import re

import httpx


class LlmUnavailable(Exception):
    """Gateway not reachable, timeout, overloaded or key rejected: release the work without a failed
    attempt and pause (AK-42)."""

    def __init__(self, message: str, key_rejected: bool = False):
        super().__init__(message)
        self.key_rejected = key_rejected


class LlmError(Exception):
    """The gateway rejected this request (e.g. 400): a normal failed attempt with backoff."""


class InvalidAnswer(Exception):
    """The answer is not usable (no JSON, required parts missing): retried once, then failed (AK-43/44)."""


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_json(text: str) -> dict:
    """JSON object from an LLM answer; thinking blocks and code fences are ignored."""
    text = _THINK.sub("", text or "").strip()
    text = _FENCE.sub("", text).strip()
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise InvalidAnswer("kein gültiges JSON") from None
        try:
            value = json.loads(text[start:end + 1])
        except ValueError:
            raise InvalidAnswer("kein gültiges JSON") from None
    if not isinstance(value, dict):
        raise InvalidAnswer("Antwort ist kein JSON-Objekt")
    return value


class LlmClient:
    def __init__(self, base_url: str, key: str, model: str, timeout: float, max_tokens: int,
                 client: httpx.AsyncClient | None = None):
        self.model = model
        self.max_tokens = max_tokens
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self.headers = headers
        self.calls = 0

    async def close(self) -> None:
        await self.http.aclose()

    async def chat(self, system: str, user: str, temperature: float) -> str:
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": temperature, "max_tokens": self.max_tokens, "stream": False,
                "response_format": {"type": "json_object"}}
        if self.model:
            body["model"] = self.model
        self.calls += 1
        try:
            r = await self.http.post("/v1/chat/completions", json=body, headers=self.headers)
        except httpx.TimeoutException as exc:
            raise LlmUnavailable(f"Zeitüberschreitung beim LLM-Gateway ({exc.__class__.__name__})") from exc
        except httpx.TransportError as exc:
            raise LlmUnavailable(f"LLM-Gateway nicht erreichbar ({exc.__class__.__name__})") from exc
        if r.status_code in (401, 403):
            raise LlmUnavailable(f"LLM-Gateway lehnt den Schlüssel ab ({r.status_code})", key_rejected=True)
        if r.status_code == 429 or r.status_code >= 500:
            raise LlmUnavailable(f"LLM-Gateway antwortet {r.status_code}")
        if r.status_code >= 400:
            raise LlmError(f"LLM-Gateway lehnt die Anfrage ab ({r.status_code}): {r.text[:300]}")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise InvalidAnswer("Antwort des Gateways ohne Inhalt") from None

    async def ask(self, system: str, user: str, temperature: float, read):
        """One call plus an immediate second one if the answer is invalid (AK-43); `read` turns the JSON
        object into the result or raises InvalidAnswer. Two invalid answers → InvalidAnswer (AK-44)."""
        last: InvalidAnswer | None = None
        for _ in range(2):
            try:
                return read(parse_json(await self.chat(system, user, temperature)))
            except InvalidAnswer as exc:
                last = exc
        raise last
