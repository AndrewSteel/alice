#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh): the service is healthy against the throwaway
# PostgreSQL; a rebuild run starts, waits with a reason because the register is not reachable in the
# container test, rejects a second start and can be cancelled; a reconciliation on demand ends as
# incomplete with a reason (register/detection not reachable). Calls only from inside the container.
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import json, time, urllib.error, urllib.request

BASE = "http://localhost:8017"

def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

status, health = call("GET", "/health")
assert status == 200 and health["status"] == "healthy", health
status, run = call("POST", "/rebuilds", {"start_stage": "classify", "kind": "document", "started_by": "smoke"})
assert status == 201 and run["status"] == "running", run
for _ in range(50):
    status, p = call("GET", f"/rebuilds/{run['id']}")
    if p["status"] == "waiting":
        break
    time.sleep(0.2)
assert p["status"] == "waiting" and "Register" in p["reason"], p
assert call("GET", "/health")[1]["status"] == "warning"
status, body = call("POST", "/rebuilds", {"start_stage": "extract", "started_by": "smoke"})
assert status == 409 and body["run"]["id"] == run["id"], body
assert call("POST", f"/rebuilds/{run['id']}/cancel")[1]["status"] == "cancelled"
status, rec = call("POST", "/reconcile")
assert status == 202, rec
for _ in range(100):
    status, res = call("GET", f"/reconcile/results/{rec['id']}")
    if res["state"] != "running":
        break
    time.sleep(0.2)
assert res["state"] == "incomplete" and res["reason"], res
assert call("GET", "/rebuilds/999999")[0] == 404
print("smoke ok: run", run["id"], "result", rec["id"])
PY
