"""AK-4, EC-7, EC-8: only active admins; 401 without/invalid token, 403 for haushalt/guest; nothing changes."""
import pytest

from tests.conftest import USERS, make_token

READS = ["/etl/state", "/etl/sources?stage=classify", "/etl/sources/t00000000001", "/etl/errors",
         "/etl/rebuild/preview?start_stage=classify", "/etl/rebuilds", "/etl/rebuilds/1", "/etl/rebuilds/1/errors",
         "/etl/reconcile/results", "/etl/reconcile/results/1", "/etl/reconcile/results/1/gaps"]
ACTIONS = [("/etl/sources/t00000000001/stages/classify/retry", None),
           ("/etl/retry", {"scope": "errors", "filter": {}}),
           ("/etl/rebuilds", {"start_stage": "classify"}),
           ("/etl/rebuilds/1/pause", None), ("/etl/rebuilds/1/resume", None), ("/etl/rebuilds/1/cancel", None),
           ("/etl/reconcile", None), ("/etl/reconcile/full-rehash", None)]


async def _snapshot(env):
    return [tuple(r) for r in await env.fetch("SELECT source_id, stage, state, attempts FROM alice.source_stages "
                                              "ORDER BY 1, 2")]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nonsense"}, {"Authorization": "Basic x"}])
async def test_without_valid_token_401(env, headers):
    for path in READS:
        assert (await env.http.get(path, headers=headers)).status_code == 401, path
    for path, body in ACTIONS:
        assert (await env.http.post(path, headers=headers, json=body)).status_code == 401, path


async def test_expired_token_401(env):
    uid, _, role = USERS["admin"]
    h = {"Authorization": f"Bearer {make_token(env.priv, uid, role, exp_in=-10)}"}
    assert (await env.http.get("/etl/state", headers=h)).status_code == 401


@pytest.mark.parametrize("role", ["haushalt", "guest"])
async def test_other_roles_403_and_nothing_changes(env, role):
    await env.source(1, states={"classify": "failed_permanent"}, attempts=5)
    before = await _snapshot(env)
    for path in READS:
        assert (await env.get(path, role=role)).status_code == 403, path
    for path, body in ACTIONS:
        assert (await env.post(path, role=role, json=body)).status_code == 403, path
    assert await _snapshot(env) == before
    assert [c for c in env.fake.calls if c[0] == "POST"] == []


async def test_role_from_database_not_token(env):
    """A token claiming admin for a user who is haushalt in the DB is rejected (EC-8)."""
    uid, _, _ = USERS["haushalt"]
    h = {"Authorization": f"Bearer {make_token(env.priv, uid, 'admin')}"}
    assert (await env.http.get("/etl/state", headers=h)).status_code == 403
    assert (await env.get("/etl/state")).status_code == 200
    await env.execute("UPDATE alice.users SET role = 'haushalt' WHERE id = $1::uuid", USERS["admin"][0])
    assert (await env.get("/etl/state")).status_code == 403
    await env.execute("UPDATE alice.users SET role = 'admin', is_active = FALSE WHERE id = $1::uuid", USERS["admin"][0])
    assert (await env.get("/etl/state")).status_code == 403


async def test_health_without_token(env):
    r = await env.http.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy"
