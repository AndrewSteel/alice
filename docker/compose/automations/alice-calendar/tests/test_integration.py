"""
Integration tests against a real PostgreSQL with sql/init-schema.sql and the
migrations up to 071 applied. Skipped unless CALENDAR_TEST_DSN is set, e.g.

    CALENDAR_TEST_DSN=postgresql://user:x@172.17.0.2:5432/alice .venv/bin/pytest
"""
import os
import time
import uuid

import pytest

DSN = os.environ.get("CALENDAR_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="CALENDAR_TEST_DSN not set")

ADMIN = "a0000000-0000-0000-0000-00000000000a"
USER = "a0000000-0000-0000-0000-00000000000b"
CHILD = "a0000000-0000-0000-0000-00000000000c"
CONN = "c0000000-0000-0000-0000-000000000001"
CONN_OTHER = "c0000000-0000-0000-0000-000000000002"


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    path = tmp_path_factory.mktemp("keys") / "pub.pem"
    path.write_text(pub)
    return priv, str(path)


@pytest.fixture
async def pool(keys, monkeypatch):
    from app import auth, db

    monkeypatch.setattr(auth, "JWT_PUBLIC_KEY_PATH", keys[1])
    monkeypatch.setattr(auth, "_public_key", None)
    monkeypatch.setattr(db, "POSTGRES_DSN", DSN)
    await db.init_pool()
    p = db.pool()
    await p.execute("DELETE FROM alice.users WHERE id = ANY($1::uuid[])", [ADMIN, USER, CHILD])
    await p.execute("DELETE FROM alice.google_connections WHERE id = ANY($1::uuid[])", [CONN, CONN_OTHER])
    for uid, name, role in ((ADMIN, "it-admin", "admin"), (USER, "it-user", "user"), (CHILD, "it-child", "child")):
        await p.execute(
            "INSERT INTO alice.users (id, username, role, is_active) VALUES ($1::uuid, $2, $3, TRUE)",
            uid, name, role,
        )
        await p.execute("SELECT alice.init_user_permissions($1::uuid, $2)", uid, role)
    for cid, uid, acc in ((CONN, USER, "u@x"), (CONN_OTHER, ADMIN, "a@x")):
        await p.execute(
            "INSERT INTO alice.google_connections (id, user_id, google_account, access_token_enc, "
            "access_token_expires_at, refresh_token_enc) VALUES ($1::uuid, $2::uuid, $3, 'e', NOW(), 'r')",
            cid, uid, acc,
        )
    yield p
    await p.execute("DELETE FROM alice.users WHERE id = ANY($1::uuid[])", [ADMIN, USER, CHILD])
    # role templates may have been changed by the admin test — restore defaults
    await db.set_role_config([{"role": r, "can_use_calendar": r in ("admin", "user")}
                              for r in ("admin", "user", "guest", "child")])
    await db.close_pool()


def _token(priv, user_id, role="user", iss=None):
    import jwt

    payload = {"user_id": user_id, "role": role, "iat": int(time.time()), "exp": int(time.time()) + 300}
    if iss:
        payload["iss"] = iss
    return jwt.encode(payload, priv, algorithm="RS256")


# ---------------------------------------------------------------------------
# Selection rules (db.set_selection)
# ---------------------------------------------------------------------------
async def _sel(user):
    from app import db
    return {r["calendar_id"]: (r["is_active"], r["is_default"]) for r in await db.list_selections(user)}


async def test_first_activated_writable_calendar_becomes_default(pool):
    from app import db
    await db.set_selection(USER, CONN, "c1", True, None, writable=True)
    await db.set_selection(USER, CONN, "c2", True, None, writable=True)
    assert await _sel(USER) == {"c1": (True, True), "c2": (True, False)}


async def test_read_only_first_calendar_not_default(pool):
    from app import db
    await db.set_selection(USER, CONN, "holidays", True, None, writable=False)
    assert await _sel(USER) == {"holidays": (True, False)}
    with pytest.raises(ValueError):
        await db.set_selection(USER, CONN, "holidays", None, True, writable=False)


async def test_default_is_unique_and_deactivating_removes_it(pool):
    from app import db
    await db.set_selection(USER, CONN, "c1", True, None, writable=True)
    await db.set_selection(USER, CONN, "c2", True, None, writable=True)
    await db.set_selection(USER, CONN, "c2", None, True, writable=True)
    assert await _sel(USER) == {"c1": (True, False), "c2": (True, True)}
    await db.set_selection(USER, CONN, "c2", False, None, writable=True)
    # no automatic successor; inactive row removed
    assert await _sel(USER) == {"c1": (True, False)}


async def test_default_requires_active(pool):
    from app import db
    with pytest.raises(ValueError):
        await db.set_selection(USER, CONN, "c9", None, True, writable=True)


async def test_selection_cannot_reference_foreign_connection(pool):
    import asyncpg
    from app import db
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await db.set_selection(USER, CONN_OTHER, "c1", True, None, writable=True)


async def test_disconnect_cascades(pool):
    from app import db
    await db.set_selection(USER, CONN, "c1", True, None, writable=True)
    await pool.execute("DELETE FROM alice.google_connections WHERE id = $1::uuid", CONN)
    assert await _sel(USER) == {}


async def test_permission_flags(pool):
    from app import db
    assert await db.can_use_calendar(ADMIN)
    assert await db.can_use_calendar(USER)
    assert not await db.can_use_calendar(CHILD)
    assert not await db.can_use_calendar("00000000-0000-0000-0000-000000000000")
    assert not await db.can_use_calendar(str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------
@pytest.fixture
async def api(pool, keys):
    import httpx
    from app import main

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, keys[0]


async def test_tab_requires_calendar_permission(api):
    client, priv = api
    r = await client.get("/calendar/accounts", headers={"Authorization": f"Bearer {_token(priv, CHILD, 'child')}"})
    assert r.status_code == 403
    r = await client.put("/calendar/selection", json={"connection_id": CONN, "calendar_id": "c1", "is_active": True},
                         headers={"Authorization": f"Bearer {_token(priv, CHILD, 'child')}"})
    assert r.status_code == 403
    r = await client.get("/calendar/accounts")
    assert r.status_code == 401


async def test_tool_forbidden_and_unknown_speaker(api):
    client, priv = api
    r = await client.post("/internal/tools/list_events", json={"args": {"range": "today"}},
                          headers={"Authorization": f"Bearer {_token(priv, CHILD, 'child')}"})
    assert r.status_code == 200 and r.json()["error"] == "forbidden"
    nil = _token(priv, "00000000-0000-0000-0000-000000000000", iss="alice-speech-gateway")
    r = await client.post("/internal/tools/create_event", json={"args": {"title": "x", "date": "2030-01-01"}},
                          headers={"Authorization": f"Bearer {nil}"})
    assert r.json()["error"] == "unknown_speaker"
    r = await client.post("/internal/tools/nope", json={}, headers={"Authorization": f"Bearer {_token(priv, USER)}"})
    assert r.status_code == 404


async def test_voice_token_role_claim_is_ignored(api):
    """Gateway tokens always claim role=user; the DB flag decides (child → forbidden)."""
    client, priv = api
    tok = _token(priv, CHILD, role="user", iss="alice-speech-gateway")
    r = await client.post("/internal/tools/list_events", json={"args": {}},
                          headers={"Authorization": f"Bearer {tok}"})
    assert r.json()["error"] == "forbidden"


async def test_admin_roles_endpoint(api):
    client, priv = api
    user_hdr = {"Authorization": f"Bearer {_token(priv, USER, role='admin')}"}  # forged role claim
    assert (await client.get("/calendar/admin/roles", headers=user_hdr)).status_code == 403
    hdr = {"Authorization": f"Bearer {_token(priv, ADMIN, 'admin')}"}
    r = await client.get("/calendar/admin/roles", headers=hdr)
    assert {x["role"]: x["can_use_calendar"] for x in r.json()["roles"]} == \
        {"admin": True, "user": True, "guest": False, "child": False}
    r = await client.put("/calendar/admin/roles", json={"roles": [{"role": "child", "can_use_calendar": True}]},
                         headers=hdr)
    assert r.status_code == 200
    from app import db
    assert await db.can_use_calendar(CHILD)       # per-user flag kept in step
    r = await client.put("/calendar/admin/roles", json={"roles": [{"role": "root", "can_use_calendar": True}]},
                         headers=hdr)
    assert r.status_code == 422


async def test_role_revocation_locks_immediately(api):
    client, priv = api
    hdr = {"Authorization": f"Bearer {_token(priv, ADMIN, 'admin')}"}
    await client.put("/calendar/admin/roles", json={"roles": [{"role": "user", "can_use_calendar": False}]},
                     headers=hdr)
    r = await client.get("/calendar/accounts", headers={"Authorization": f"Bearer {_token(priv, USER)}"})
    assert r.status_code == 403


async def test_pending_question_survives_to_next_turn_only(api, monkeypatch):
    """confirm_delete result is remembered for turn+1; same-turn errors don't clear it."""
    from app import agent, tickets
    from tests.conftest import FakeRedis

    fake = FakeRedis()
    tickets.set_client(fake)
    client, priv = api
    hdr = {"Authorization": f"Bearer {_token(priv, USER)}"}

    async def fake_prepare(ctx, args):
        return {"status": "confirm_delete", "ticket": "T1", "event": {"title": "Zahnarzt"}, "instruction": "x"}

    async def fake_confirm(ctx, args):
        return agent._err("ticket_same_turn", "x")

    monkeypatch.setitem(__import__("app.main", fromlist=["_TOOLS"])._TOOLS, "delete_event", fake_prepare)
    monkeypatch.setitem(__import__("app.main", fromlist=["_TOOLS"])._TOOLS, "confirm_delete", fake_confirm)
    try:
        await client.post("/internal/tools/delete_event", headers=hdr,
                          json={"args": {"title_query": "Zahnarzt"}, "session_id": "s1", "turn": 3})
        await client.post("/internal/tools/confirm_delete", headers=hdr,
                          json={"args": {"ticket": "T1"}, "session_id": "s1", "turn": 3})
        nxt = (await client.post("/internal/turn", headers=hdr, json={"session_id": "s1", "turn": 4})).json()
        assert nxt["enabled"] and nxt["pending"]["result"]["ticket"] == "T1"
        assert "instruction" not in nxt["pending"]["result"]
        later = (await client.post("/internal/turn", headers=hdr, json={"session_id": "s1", "turn": 5})).json()
        assert later["pending"] is None
        other = (await client.post("/internal/turn", headers=hdr, json={"session_id": "s2", "turn": 4})).json()
        assert other["pending"] is None
        child = (await client.post("/internal/turn", json={"session_id": "s1", "turn": 4},
                                   headers={"Authorization": f"Bearer {_token(priv, CHILD, 'child')}"})).json()
        assert child == {"enabled": False, "reason": "forbidden", "pending": None}
    finally:
        tickets.set_client(None)


async def test_bug1_first_writable_after_read_only_becomes_default(pool):
    from app import db
    await db.set_selection(USER, CONN, "holidays", True, None, writable=False)
    await db.set_selection(USER, CONN, "privat", True, None, writable=True)
    await db.set_selection(USER, CONN, "family", True, None, writable=True)
    assert await _sel(USER) == {"holidays": (True, False), "privat": (True, True), "family": (True, False)}


async def test_bug3_complex_recurrence_mentions_google(api):
    client, priv = api
    r = await client.post("/internal/tools/create_event", headers={"Authorization": f"Bearer {_token(priv, USER)}"},
                          json={"args": {"title": "x", "date": "2030-01-01",
                                         "recurrence": {"freq": "monthly", "interval": 2}},
                                "session_id": "s", "turn": 1})
    body = r.json()
    assert body["error"] == "unsupported_recurrence" and "Google" in body["message"]
