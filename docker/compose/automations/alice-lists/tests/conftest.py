"""
Shared fixtures. The DB-backed tests need a PostgreSQL with sql/init-schema.sql
and the migrations up to 072 applied; they are skipped unless LISTS_TEST_DSN
is set, e.g.

    LISTS_TEST_DSN=postgresql://user:x@localhost:55432/alice .venv/bin/pytest

Redis is replaced by an in-memory fake.
"""
import os
from datetime import datetime

import pytest

from app import agent, tickets
from app import timeutil as tu

TZ = tu.zone("Europe/Berlin")
DSN = os.environ.get("LISTS_TEST_DSN")

ADMIN = "b0000000-0000-0000-0000-00000000000a"
USER = "b0000000-0000-0000-0000-00000000000b"
USER2 = "b0000000-0000-0000-0000-00000000000d"
CHILD = "b0000000-0000-0000-0000-00000000000c"
GUEST = "b0000000-0000-0000-0000-00000000000e"
USERS = ((ADMIN, "lt-admin", "admin"), (USER, "lt-user", "user"), (USER2, "lt-user2", "user"),
         (CHILD, "lt-child", "child"), (GUEST, "lt-guest", "guest"))
ROLE_OF = {uid: role for uid, _, role in USERS}


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


@pytest.fixture(autouse=True)
def fake_redis():
    fake = FakeRedis()
    tickets.set_client(fake)
    yield fake
    tickets.set_client(None)


@pytest.fixture
async def pool(monkeypatch):
    if not DSN:
        pytest.skip("LISTS_TEST_DSN not set")
    from app import db

    monkeypatch.setattr(db, "POSTGRES_DSN", DSN)
    await db.init_pool()
    p = db.pool()
    await p.execute("DELETE FROM alice.users WHERE id = ANY($1::uuid[])", [u[0] for u in USERS])
    # The test DB is disposable: start every test from the migration state.
    await p.execute("DELETE FROM alice.lists")
    await p.execute("INSERT INTO alice.lists (name, is_shared, is_shopping) VALUES ('Einkaufsliste', TRUE, TRUE)")
    for uid, name, role in USERS:
        await p.execute("INSERT INTO alice.users (id, username, role, is_active) VALUES ($1::uuid, $2, $3, TRUE)",
                        uid, name, role)
        await p.execute("SELECT alice.init_user_permissions($1::uuid, $2)", uid, role)
    yield p
    await p.execute("DELETE FROM alice.users WHERE id = ANY($1::uuid[])", [u[0] for u in USERS])
    await db.set_role_config([{"role": r, "can_use_lists": r != "guest"} for r in ("admin", "user", "guest", "child")])
    await db.close_pool()


def make_ctx(user_id, *, turn=1, session="s1", channel="chat", confirmed=False, now=None):
    return agent.Ctx(
        user_id=user_id, role=ROLE_OF.get(user_id), tz=TZ, now=now or datetime.now(TZ),
        channel=channel, session_id=session, turn=turn, confirmed=confirmed,
    )
