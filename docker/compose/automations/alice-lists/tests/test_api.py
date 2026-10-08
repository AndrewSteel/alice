"""HTTP layer (app.main) against the test DB: auth, admin role config, turn
start, and the server-side gate on confirmed=true."""
import time

import pytest

from tests.conftest import ADMIN, GUEST, USER

pytestmark = pytest.mark.usefixtures("pool")
NIL = "00000000-0000-0000-0000-000000000000"


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
async def client(keys, monkeypatch):
    import httpx
    from app import auth

    monkeypatch.setattr(auth, "JWT_PUBLIC_KEY_PATH", keys[1])
    monkeypatch.setattr(auth, "_public_key", None)
    from app import main

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        yield c


def _auth(keys, user_id, role="user"):
    import jwt

    now = int(time.time())
    tok = jwt.encode({"user_id": user_id, "role": role, "iat": now, "exp": now + 300}, keys[0], algorithm="RS256")
    return {"Authorization": f"Bearer {tok}"}


async def _tool(client, keys, user, tool, args, turn=1, session="s1"):
    r = await client.post(f"/internal/tools/{tool}", headers=_auth(keys, user),
                          json={"args": args, "session_id": session, "turn": turn})
    assert r.status_code == 200
    return r.json()


async def test_requires_valid_jwt(client):
    assert (await client.post("/internal/tools/query_items", json={})).status_code == 401
    r = await client.post("/internal/tools/query_items", json={}, headers={"Authorization": "Bearer x"})
    assert r.status_code == 401


async def test_admin_roles_endpoint(client, keys):
    assert (await client.get("/lists/admin/roles", headers=_auth(keys, USER))).status_code == 403
    # a forged admin claim does not help — the role is read from the DB
    assert (await client.get("/lists/admin/roles", headers=_auth(keys, USER, "admin"))).status_code == 403
    r = await client.get("/lists/admin/roles", headers=_auth(keys, ADMIN, "admin"))
    assert r.status_code == 200
    assert {x["role"]: x["can_use_lists"] for x in r.json()["roles"]} == \
        {"admin": True, "user": True, "child": True, "guest": False}
    r = await client.put("/lists/admin/roles", headers=_auth(keys, ADMIN, "admin"),
                         json={"roles": [{"role": "user", "can_use_lists": False}]})
    assert r.status_code == 200
    res = await _tool(client, keys, USER, "query_items", {})
    assert res["error"] == "forbidden"
    r = await client.put("/lists/admin/roles", headers=_auth(keys, ADMIN, "admin"),
                         json={"roles": [{"role": "boss", "can_use_lists": True}]})
    assert r.status_code == 422


async def test_turn_start(client, keys):
    r = (await client.post("/internal/turn", headers=_auth(keys, GUEST), json={"session_id": "s", "turn": 1})).json()
    assert r == {"enabled": False, "reason": "forbidden", "pending": None}
    r = (await client.post("/internal/turn", headers=_auth(keys, NIL), json={"session_id": "s", "turn": 1})).json()
    assert r["enabled"] and r["unknown_speaker"]
    r = (await client.post("/internal/turn", headers=_auth(keys, USER), json={"session_id": "s", "turn": 1})).json()
    assert r["enabled"] and r["pending"] is None


async def test_unknown_tool_404(client, keys):
    r = await client.post("/internal/tools/drop_all", headers=_auth(keys, USER), json={})
    assert r.status_code == 404


async def test_confirmed_only_counts_as_answer_to_open_question(client, keys):
    # Unprompted confirmed=true is ignored: the past date is still asked about.
    res = await _tool(client, keys, USER, "add_items", {"items": "Alt", "due_date": "2020-01-01", "confirmed": True})
    assert res["status"] == "confirm_past"
    # Turn start of the next turn hands the question back ...
    r = (await client.post("/internal/turn", headers=_auth(keys, USER), json={"session_id": "s1", "turn": 2})).json()
    assert r["pending"]["result"]["status"] == "confirm_past" and r["pending"]["tool"] == "add_items"
    # ... and the confirmed answer in that turn is honoured.
    res = await _tool(client, keys, USER, "add_items", {"items": "Alt", "due_date": "2020-01-01", "confirmed": True},
                      turn=2)
    assert res["status"] == "added"
    # resolved → no pending question any more
    r = (await client.post("/internal/turn", headers=_auth(keys, USER), json={"session_id": "s1", "turn": 3})).json()
    assert r["pending"] is None


async def test_unknown_speaker_over_http(client, keys):
    res = await _tool(client, keys, NIL, "add_items", {"items": "Milch", "list": "Einkaufsliste"})
    assert res["status"] == "added"
    res = await _tool(client, keys, NIL, "query_items", {"list": "Einkaufsliste"})
    assert res["error"] == "unknown_speaker"


async def test_invalid_input_is_reported(client, keys):
    res = await _tool(client, keys, USER, "add_items", {"items": "x", "due_date": "morgen"})
    assert res["error"] == "invalid_input"
    res = await _tool(client, keys, USER, "manage_list", {"action": "explode"})
    assert res["error"] == "invalid_input"


async def test_delete_flow_over_http(client, keys):
    await _tool(client, keys, USER, "add_items", {"items": "Reifen wechseln"}, turn=1)
    q = await _tool(client, keys, USER, "remove_items", {"items": "Reifen wechseln"}, turn=2)
    assert q["status"] == "confirm_delete"
    r = (await client.post("/internal/turn", headers=_auth(keys, USER), json={"session_id": "s1", "turn": 3})).json()
    assert r["pending"]["result"]["ticket"] == q["ticket"]
    d = await _tool(client, keys, USER, "confirm_delete", {"ticket": q["ticket"]}, turn=3)
    assert d["status"] == "deleted"
