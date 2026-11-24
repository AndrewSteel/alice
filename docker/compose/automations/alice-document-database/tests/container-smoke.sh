#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh):
# 1. the service runs and reports the unreachable register (no register in the container test) with its
#    reason: as a warning within DATABASE_REGISTRY_GRACE_SECONDS (60 s), afterwards as unhealthy;
#    /status answers with the default concurrency 2;
# 2. inside the image: one invoice is written end to end against a fake register (httpx MockTransport)
#    into the throwaway PostgreSQL of the container test (POSTGRES_DSN), then removed as deleted.
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import json, time, urllib.error, urllib.request

def call(path):
    try:
        with urllib.request.urlopen("http://localhost:8016" + path, timeout=10) as r:
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
assert status == 200 and body["active"] == [] and body["concurrency"] == 2, body
print("smoke ok: health", health["status"])
PY
docker exec -i "$CT_CONTAINER" python - <<'PY'
import asyncio, json, os, uuid
from decimal import Decimal
import httpx
from app.config import Settings
from app.registry import RegistryClient
from app.store import Store
from app.worker import Worker

SID = "smoketest0001"[:12]
state = {"round": 0}
FM = {"type": "Invoice", "title": "Rechnung", "summary": "Eine Rechnung.", "language": "de",
      "captured": "2026-11-05T10:00:00+00:00", "locations": [{"path": "/mnt/nas/x/r.pdf"}],
      "classification": {"confidence": 0.9, "uncertain": False}, "summary_language_uncertain": False,
      "fields": {"amount_gross": 1250000.01, "invoice_date": "2026-10-14",
                 "line_items": [{"description": "A", "quantity": 0.000123, "amount": 1.5}]}}

def register(req):
    path = req.url.path
    if path.endswith("/claim"):
        body = json.loads(req.content)
        assert body == {"limit": 2, "kinds": ["document"], "requires": ["classify"], "include_deleted": True}, body
        state["round"] += 1
        items = {1: [{"source_id": SID, "token": str(uuid.uuid4()), "deleted": False}],
                 2: [{"source_id": SID, "token": str(uuid.uuid4()), "deleted": True}]}.get(state["round"], [])
        return httpx.Response(200, json={"paused": False, "items": items})
    if path.endswith("/document"):
        return httpx.Response(200, text=json.dumps({"path": "documents/r.md", "frontmatter": FM, "content": ""}))
    state.setdefault("calls", []).append(path.rsplit("/", 1)[1])
    return httpx.Response(200, json={})

async def main():
    s = Settings(postgres_dsn=os.environ["POSTGRES_DSN"], poll_seconds=0.01)
    reg = RegistryClient("http://r", client=httpx.AsyncClient(base_url="http://r", transport=httpx.MockTransport(register)))
    store = Store(s.postgres_dsn)
    w = Worker(s, reg, store)
    await w.step(); await w.wait_idle()
    pool = await store.connect()
    row = await pool.fetchrow("SELECT amount_gross, invoice_date::text FROM alice.doc_invoices WHERE document_id = $1", SID)
    assert row and row[0] == Decimal("1250000.01") and row[1] == "2026-10-14", row
    q = await pool.fetchval("SELECT quantity FROM alice.doc_invoice_line_items WHERE document_id = $1", SID)
    assert q == Decimal("0.000123"), q
    await w.step(); await w.wait_idle()
    assert await pool.fetchval("SELECT count(*) FROM alice.doc_documents WHERE id = $1", SID) == 0
    assert state["calls"] == ["done", "done"], state
    await store.close()
    print("selftest ok: written and removed")

asyncio.run(main())
PY
