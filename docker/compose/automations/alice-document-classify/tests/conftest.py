"""
Shared fixtures.

- FakeGateway: OpenAI compatible stand-in for alice-llm-gateway (httpx MockTransport). It records
  every request (task, temperature, prompts, key) and answers from scripted queues per task
  (`classify`, `extract`, `transactions`, read from the `TASK:` line of the system prompt).
- FakeRegistry: in-memory stand-in for the interface of alice-source-registry.
  End-to-end tests against the real register code use TEST_POSTGRES_DSN (test_e2e.py).
"""
from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest

from app.classifier import Classifier
from app.config import Settings
from app.llm import LlmClient

KEY = "test-background-key"


def answer(obj) -> str:
    return obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)


class FakeGateway:
    def __init__(self):
        self.requests: list[dict] = []
        self.queues: dict[str, list] = {"classify": [], "extract": [], "transactions": []}
        self.defaults = {
            "classify": {"type": "Document", "confidence": 0.9},
            "extract": {"title": "Schreiben der Stadtwerke", "summary": "Ein Schreiben der Stadtwerke "
                        "über die neue Abrechnung. Es enthält keine weiteren Angaben.", "fields": {}},
            "transactions": {"transactions": []},
        }
        self.down = False  # raise a connect error
        self.status = 200

    def push(self, task: str, *answers):
        self.queues[task].extend(answers)

    def calls(self, task: str | None = None) -> list[dict]:
        return [r for r in self.requests if task is None or r["task"] == task]

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("gateway down", request=request)
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        task = system.split("\n", 1)[0].removeprefix("TASK: ").strip()
        self.requests.append({"task": task, "temperature": body.get("temperature"), "system": system,
                              "user": body["messages"][1]["content"], "auth": request.headers.get("authorization"),
                              "url": str(request.url), "model": body.get("model")})
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        q = self.queues[task]
        content = q.pop(0) if q else self.defaults[task]
        if callable(content):
            content = content(self.requests[-1])
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": answer(content)}}]})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url="http://alice-llm-gateway:8011", transport=httpx.MockTransport(self.handler))


@pytest.fixture
def settings():
    return Settings(poll_seconds=0.01, heartbeat_seconds=3600, registry_grace_seconds=0, gateway_key=KEY,
                    model="test-model", llm_retry_seconds=60)


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def llm(settings, gateway):
    return LlmClient(settings.gateway_url, settings.gateway_key, settings.model, 5, 1000, client=gateway.client())


@pytest.fixture
def classifier(settings, llm):
    return Classifier(settings, llm)


def frontmatter(**kw) -> dict:
    fm = {"id": "abcdefghijkl", "schema": 1, "kind": "document", "title": "scan.pdf",
          "locations": [{"path": "/mnt/nas/share/scan.pdf"}], "parents": [], "hash": "sha256:x", "size": 1,
          "modified": "2026-10-14T07:32:11+00:00", "captured": "2026-11-01T10:00:00+00:00", "language": "de",
          "type": None, "manual": [], "extraction": {"method": "text", "ocr_pages": [], "empty": False}}
    fm.update(kw)
    return fm


# ---------------------------------------------------------------- fake register
class FakeRegistry:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.queue: list[str] = []
        self.calls: list[tuple] = []
        self.written: dict[str, dict] = {}
        self.state: dict[str, str] = {}
        self.unavailable = False
        self.discard = False
        self.running = 0
        self.max_running = 0

    def add(self, sid, content="Rechnung", **fm):
        self.docs[sid] = {"id": sid, "frontmatter": frontmatter(id=sid, **fm), "content": content}
        self.queue.append(sid)
        self.state[sid] = "pending"

    def _check(self):
        if self.unavailable:
            from app.registry import RegistryUnavailable

            raise RegistryUnavailable("Register nicht erreichbar: ConnectError")

    async def claim(self, limit):
        self._check()
        items = []
        while self.queue and len(items) < limit:
            sid = self.queue.pop(0)
            self.state[sid] = "running"
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            items.append({"source_id": sid, "token": str(uuid.uuid4()), "kind": "document",
                          "title": self.docs[sid]["frontmatter"]["title"]})
        self.calls.append(("claim", limit, len(items)))
        return {"paused": False, "reason": None, "items": items}

    async def read_document(self, sid):
        self._check()
        await asyncio.sleep(0)
        return self.docs[sid]

    async def write(self, sid, *, fields, token, batch):
        self._check()
        self.calls.append(("write", sid, batch))
        if self.discard:
            return {"discarded": True, "changed": False}
        self.written[sid] = {"fields": fields, "batch": batch, "token": token}
        return {"changed": True}

    def _end(self, sid, state):
        self.state[sid] = state
        self.running -= 1

    async def done(self, sid, token):
        self.calls.append(("done", sid))
        self._end(sid, "done")

    async def fail(self, sid, token, error, permanent=False):
        self.calls.append(("fail", sid, error, permanent))
        self._end(sid, "failed_permanent" if permanent else "failed")

    async def release(self, sid, token, delay_seconds=0):
        self.calls.append(("release", sid, delay_seconds))
        self._end(sid, "pending")

    async def heartbeat(self, sid, token):
        self.calls.append(("heartbeat", sid))
        return {"state": "running"}


@pytest.fixture
def registry():
    return FakeRegistry()


async def drain(worker, rounds=200):
    for _ in range(rounds):
        await worker.step()
        await asyncio.sleep(0)
        if not worker.registry.queue and not worker.active:
            return
    await worker.wait_idle()
