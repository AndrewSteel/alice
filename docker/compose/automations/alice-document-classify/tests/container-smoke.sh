#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh):
# 1. the service runs and reports the unreachable register (no register in the container test) with its
#    reason: as a warning within CLASSIFY_REGISTRY_GRACE_SECONDS (60 s), afterwards as unhealthy;
#    /status answers with concurrency 1 (AK-41);
# 2. inside the image: one source is classified end to end against an in-process fake register and a
#    fake OpenAI compatible gateway (both on localhost), with the installed packages only.
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import json, time, urllib.error, urllib.request

def call(path):
    try:
        with urllib.request.urlopen("http://localhost:8015" + path, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

for _ in range(30):
    status, health = call("/health")
    if health["warnings"] or health["errors"]:
        break
    time.sleep(1)
assert (status, health["status"]) in ((200, "warning"), (503, "unhealthy")), health
assert any("Register nicht erreichbar" in w for w in health["warnings"] + health["errors"]), health
status, body = call("/status")
assert status == 200 and body["active"] == [] and body["concurrency"] == 1, body
print("smoke ok: health", health["status"])
PY
docker exec -i "$CT_CONTAINER" python - <<'PY'
import asyncio, json, uuid
import httpx
from app.classifier import Classifier
from app.config import Settings
from app.llm import LlmClient
from app.registry import RegistryClient
from app.worker import Worker

answers = {"classify": {"type": "Invoice", "confidence": 0.9},
           "extract": {"title": "Stromrechnung Stadtwerke", "summary": "Die Stadtwerke rechnen ab.",
                       "fields": {"amount_gross": "119,00", "currency": "EUR"}}}
seen = []

def gateway(req):
    body = json.loads(req.content)
    task = body["messages"][0]["content"].split("\n", 1)[0].removeprefix("TASK: ")
    seen.append((task, req.headers.get("authorization")))
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answers[task])}}]})

state = {}

def register(req):
    path = req.url.path
    if path.endswith("/claim"):
        body = json.loads(req.content)
        assert body == {"limit": 1, "kinds": ["document"], "requires": ["extract"]}, body
        items = [] if state else [{"source_id": "abcdefghijkl", "token": str(uuid.uuid4())}]
        return httpx.Response(200, json={"paused": False, "items": items})
    if path.endswith("/document") and req.method == "GET":
        fm = {"title": "scan.pdf", "modified": "2026-10-14T07:32:11+00:00", "language": "de", "manual": [],
              "extraction": {"empty": False}, "locations": [{"path": "/mnt/nas/x/scan.pdf"}]}
        return httpx.Response(200, json={"frontmatter": fm, "content": "Rechnung 119,00 EUR"})
    if path.endswith("/document"):
        state["written"] = json.loads(req.content)
        return httpx.Response(200, json={"changed": True})
    state[path.rsplit("/", 1)[1]] = True
    return httpx.Response(200, json={})

async def main():
    s = Settings(gateway_key="k", poll_seconds=0.01)
    reg = RegistryClient("http://r", client=httpx.AsyncClient(base_url="http://r", transport=httpx.MockTransport(register)))
    llm = LlmClient("http://g", "k", "", 5, 100, client=httpx.AsyncClient(base_url="http://g", transport=httpx.MockTransport(gateway)))
    w = Worker(s, reg, Classifier(s, llm))
    await w.step()
    await w.wait_idle()
    f = state["written"]["fields"]
    assert state.get("done") and f["type"] == "Invoice", state
    assert f["title"] == "2026-10-14 09.32.11 Stromrechnung Stadtwerke", f["title"]
    assert f["fields"]["amount_gross"] == 119.0
    assert seen == [("classify", "Bearer k"), ("extract", "Bearer k")], seen
    print("selftest ok:", f["title"])

asyncio.run(main())
PY
