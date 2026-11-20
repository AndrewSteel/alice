"""PROJ-121: only admin / haushalt / guest may be assigned (AK-1, AK-8, AK-13, AK-15)."""
import os
import uuid

import psycopg2
import pytest

import main
from tests.conftest import token

NEEDS_DB = pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_DSN"), reason="TEST_POSTGRES_DSN not set")


def _create(client, role, auth_role="admin", username=None):
    return client.post(
        "/auth/admin/users",
        json={"username": username or f"t_{uuid.uuid4().hex[:10]}",
              "email": f"{uuid.uuid4().hex[:10]}@example.com", "role": role},
        headers={"Authorization": f"Bearer {token(auth_role)}"},
    )


@pytest.mark.parametrize("role", ["user", "child", "Haushalt", ""])
def test_legacy_and_unknown_roles_rejected(client, role):
    r = _create(client, role)
    assert r.status_code == 422
    assert "admin, haushalt, guest" in r.json()["detail"]


@pytest.mark.parametrize("role", ["haushalt", "guest", "user"])
def test_user_management_admin_only(client, role):
    # A household member (or a pre-migration 'user' token) is no admin.
    r = _create(client, "haushalt", auth_role=role)
    assert r.status_code == 403
    r = client.get("/auth/admin/users", headers={"Authorization": f"Bearer {token(role)}"})
    assert r.status_code == 403


@NEEDS_DB
@pytest.mark.parametrize("role", ["admin", "haushalt", "guest"])
def test_create_user_with_new_roles(client, monkeypatch, role):
    monkeypatch.setattr(main, "_check_mx_record", lambda domain: (True, False))
    monkeypatch.setattr(main, "_send_otp_email", lambda **kw: None)
    username = f"t_{role}_{uuid.uuid4().hex[:8]}"
    r = _create(client, role, username=username)
    assert r.status_code == 201, r.text
    assert r.json()["role"] == role

    conn = psycopg2.connect(os.environ["TEST_POSTGRES_DSN"])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ps.can_manage_users, pa.can_use_timers, "
                "(SELECT COUNT(*) FROM alice.permissions_home_assistant h WHERE h.user_id = u.id) "
                "FROM alice.users u "
                "JOIN alice.permissions_system ps ON ps.user_id = u.id "
                "JOIN alice.permissions_assistant pa ON pa.user_id = u.id "
                "WHERE u.username = %s",
                (username,),
            )
            manage_users, timers, ha_domains = cur.fetchone()
            cur.execute("DELETE FROM alice.users WHERE username = %s", (username,))
        conn.commit()
    finally:
        conn.close()
    assert manage_users is (role == "admin")
    assert timers is (role != "guest")
    assert ha_domains > 0
