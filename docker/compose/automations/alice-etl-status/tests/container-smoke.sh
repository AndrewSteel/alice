#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh): admin interface inside the running image
# against the throwaway database. Register and alice-etl-rebuild are not running here: the
# state must still answer (rebuild part marked unavailable, EC-9).
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import asyncio, json, os, time, urllib.error, urllib.request

import asyncpg, jwt

IDS = {"admin": "a1220000-0000-0000-0000-00000000c001", "haushalt": "a1220000-0000-0000-0000-00000000c002"}
KEY = open("/run/secrets/jwt_private.pem").read()


def call(path, role=None, method="GET"):
    req = urllib.request.Request(f"http://localhost:8018{path}", method=method,
                                 data=b"{}" if method == "POST" else None, headers={"Content-Type": "application/json"})
    if role:
        now = int(time.time())
        tok = jwt.encode({"user_id": IDS[role], "role": role, "iat": now, "exp": now + 60}, KEY, algorithm="RS256")
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


async def users(sql):
    con = await asyncpg.connect(os.environ["POSTGRES_DSN"])
    try:
        for role, uid in IDS.items():
            await con.execute(sql, uid, f"smoke-{role}", role)
    finally:
        await con.close()


asyncio.run(users("INSERT INTO alice.users (id, username, role) VALUES ($1::uuid, $2, $3) "
                  "ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role, is_active = TRUE"))
try:
    assert call("/health")[0] == 200
    assert call("/etl/state")[0] == 401
    assert call("/etl/state", "haushalt")[0] == 403
    assert call("/etl/retry", "haushalt", "POST")[0] == 403
    st, body = call("/etl/state", "admin")
    assert st == 200, body
    assert body["stages"][0] == "detect" and body["services"]["rebuild"] is False, body
    st, body = call("/etl/rebuild/preview?start_stage=classify", "admin")
    assert st == 200 and body["stages"][0] == "classify", body
finally:
    asyncio.run(users("DELETE FROM alice.users WHERE id = $1::uuid AND $2::text IS NOT NULL AND $3::text IS NOT NULL"))
print("alice-etl-status smoke OK")
PY
