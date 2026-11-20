#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh): PROJ-121 role validation
# against the running service and the throwaway database.
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import json
import urllib.error
import urllib.request

import main  # same env as the service: signs test tokens with the test key

BASE = "http://localhost:8002"


def call(method, path, role, body=None):
    tok = main._create_jwt("a1210000-0000-0000-0000-0000000000aa", f"smoke-{role}", role)
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


for legacy in ("user", "child"):
    st = call("POST", "/auth/admin/users", "admin",
              {"username": f"smoke_{legacy}", "email": "smoke@example.com", "role": legacy})
    assert st == 422, (legacy, st)
for role in ("haushalt", "guest"):
    st = call("GET", "/auth/admin/users", role)
    assert st == 403, (role, st)
assert call("GET", "/auth/admin/users", "admin") == 200
print("alice-auth smoke OK")
PY
