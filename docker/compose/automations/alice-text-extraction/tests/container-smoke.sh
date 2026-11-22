#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh):
# 1. the service runs and reports the unreachable register (no register in the container test)
#    with its reason: as a warning within EXTRACT_REGISTRY_GRACE_SECONDS (60 s), afterwards as
#    unhealthy (AK-35); /status answers;
# 2. real extraction inside the image as the non-root NAS account: LibreOffice converts generated
#    documents into every supported Office / OpenDocument variant, Tesseract reads a scanned page
#    (tests/container_selftest.py).
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import json, time, urllib.error, urllib.request

def call(path):
    try:
        with urllib.request.urlopen("http://localhost:8014" + path, timeout=10) as r:
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
docker exec -i -u 1000:100 "$CT_CONTAINER" python - <"$(dirname "$0")/container_selftest.py"
