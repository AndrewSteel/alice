#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh): the service is healthy, a
# manually triggered day scan and nightly run finish (no watched folders in the
# throwaway database, so the register is not needed) and a second trigger while
# a run is active is refused. Calls only from inside the container.
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import json, time, urllib.error, urllib.request

BASE = "http://localhost:8013"

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
for kind in ("day", "night"):
    for _ in range(50):  # the scheduler may be running its first day scan
        status, body = call("POST", f"/runs/{kind}")
        if status == 202:
            break
        assert status == 409 and body["error"] == "busy", body
        time.sleep(0.2)
    assert status == 202, body
    for _ in range(50):
        runs = call("GET", f"/runs?kind={kind}&limit=1")[1]["runs"]
        if runs and runs[0]["state"] != "running":
            break
        time.sleep(0.2)
    assert runs[0]["state"] == "done" and runs[0]["trigger"] == "manual", runs
night = call("GET", "/runs?kind=night&limit=1")[1]["runs"][0]
assert night["summary"]["files_scanned"] == 0 and night["summary"]["problems"]["count"] == 0, night
assert call("GET", "/problems")[1] == {"count": 0, "items": []}
# PROJ-120: reconciliation lease and level 1 check (no watched folders: nothing to report)
status, lease = call("POST", "/reconcile/lease", {"seconds": 60})
assert status == 200, lease
assert call("POST", "/reconcile/lease", {"seconds": 60})[0] == 409
status, check = call("POST", "/reconcile/check")
assert status == 200 and check["unregistered"] == [] and check["missing"] == [], check
assert call("DELETE", f"/reconcile/lease/{lease['token']}")[1] == {"released": True}
print("smoke ok: runs", night["id"])
PY
