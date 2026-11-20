#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh): PROJ-121 archive access by
# DB role and role validation of the timer config, inside the running image
# against the throwaway database.
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import asyncio

from pydantic import ValidationError

from app import memory, tools
from app.main import TimerConfigUpdate

IDS = {
    "admin": "a1210000-0000-0000-0000-00000000c001",
    "haushalt": "a1210000-0000-0000-0000-00000000c002",
    "guest": "a1210000-0000-0000-0000-00000000c003",
}


async def main():
    await memory.init_pool()
    pool = memory.pool()
    for role, uid in IDS.items():
        await pool.execute(
            "INSERT INTO alice.users (id, username, role) VALUES ($1::uuid, $2, $3) "
            "ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role, is_active = TRUE",
            uid, f"smoke-{role}", role)
    try:
        assert await tools.archive_access(IDS["admin"]) is True
        assert await tools.archive_access(IDS["haushalt"]) is True
        assert await tools.archive_access(IDS["guest"]) is False
        # unrecognised speaker (voice-guest from init-schema.sql)
        assert await tools.archive_access("00000000-0000-0000-0000-000000000000") is False
        await pool.execute("UPDATE alice.users SET is_active = FALSE WHERE id = $1::uuid", IDS["haushalt"])
        assert await tools.archive_access(IDS["haushalt"]) is False
        for legacy in ("user", "child"):
            try:
                await pool.execute("UPDATE alice.users SET role = $2 WHERE id = $1::uuid", IDS["guest"], legacy)
            except Exception:
                pass
            else:
                raise AssertionError(f"DB accepted legacy role {legacy}")
    finally:
        await pool.execute("DELETE FROM alice.users WHERE id = ANY($1::uuid[])", list(IDS.values()))
        await memory.close_pool()


asyncio.run(main())

for bad in ({"default_role": "user"}, {"default_role": "child"},
            {"roles": [{"role": "user", "can_use_timers": True, "timer_max_active": 1,
                        "timer_max_duration_seconds": 60}]}):
    try:
        TimerConfigUpdate(**bad)
    except ValidationError:
        continue
    raise AssertionError(f"accepted {bad}")
TimerConfigUpdate(default_role="haushalt", roles=[{"role": "haushalt", "can_use_timers": True,
                                                   "timer_max_active": 10, "timer_max_duration_seconds": 86400}])
print("alice-chat-stream smoke OK")
PY
