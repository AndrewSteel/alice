#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh): the service initialized the
# empty /data/sot as a git repo, registers a source, writes + commits its
# markdown and serves the work queue. Calls only from inside the container.
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import json, subprocess, urllib.request

BASE = "http://localhost:8012"

def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

health = call("GET", "/health")
assert health["status"] == "healthy", health
src = call("POST", "/sources", {"kind": "document", "hash": "sha256:smoketest0001", "title": "scan_0042.pdf",
                                "location": {"path": "/smoke/scan_0042.pdf"}})
assert src["path"].startswith("documents/") and src["path"].endswith("-scan-0042-pdf.md"), src
log = subprocess.run(["git", "-c", "safe.directory=*", "-C", "/data/sot", "log", "--format=%an|%s"],
                     capture_output=True, text=True, check=True).stdout.splitlines()
assert log[0] == f"Alice ETL|detect: {src['id']} scan_0042.pdf", log
assert log[-1] == "Alice ETL|init: source of truth repository", log
items = call("POST", "/stages/extract/claim", {"limit": 1})["items"]
assert items and items[0]["source_id"] == src["id"], items
print("smoke ok:", src["id"])
PY
