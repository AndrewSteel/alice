"""Rebuild and reconciliation through the PROJ-120 fake (AK-20–35, AK-41, EC-6, EC-9)."""
from datetime import datetime, timedelta, timezone


def _result(rid, state="complete", hours=2, reported=0, repaired=0):
    t = datetime.now(timezone.utc) - timedelta(hours=hours)
    return {"id": rid, "kind": "nightly", "state": state, "started_at": (t - timedelta(minutes=5)).isoformat(),
            "finished_at": t.isoformat(), "summary": {"levels": {"1": {"gaps": reported + repaired,
                                                                       "repaired": repaired, "reported": reported,
                                                                       "repair_failed": 0}}}}


async def test_preview(env):
    """AK-20: count of affected sources and the stages from classify on; detect not selectable."""
    for i in range(1, 4):
        await env.source(i)
    await env.source(4, deleted=True)
    await env.source(5, locked="kaputt")
    await env.source(6, kind="image")
    p = (await env.get("/etl/rebuild/preview", start_stage="classify", kind="document")).json()
    assert p["sources"] == 3 and p["stages"] == ["classify", "database", "rag", "wiki", "thumbnail"]
    assert (await env.get("/etl/rebuild/preview", start_stage="classify")).json()["sources"] == 4
    assert (await env.get("/etl/rebuild/preview", start_stage="classify", kind="audio")).json()["sources"] == 0
    assert (await env.get("/etl/rebuild/preview", start_stage="detect")).status_code == 422
    assert (await env.get("/etl/rebuild/preview", start_stage="unknown")).status_code == 422


async def test_start_uses_admin_name(env):
    """AK-21: started_by is the logged-in admin, never from the request body."""
    r = await env.post("/etl/rebuilds", json={"start_stage": "classify", "kind": "document", "started_by": "evil"})
    assert r.status_code == 201
    post = [c for c in env.fake.calls if c[:2] == ("POST", "/rebuilds")]
    assert post[0][2] == {"start_stage": "classify", "kind": "document", "started_by": "etl-admin"}
    st = (await env.get("/etl/state")).json()
    assert st["rebuild"]["active"] and st["rebuild"]["run"]["status"] == "running"


async def test_rejection_passed_on(env):
    """AK-42/EC-6: a 409 of PROJ-120 reaches the page with its reason."""
    env.fake.reject["POST /rebuilds"] = (409, {"error": "conflict", "detail": "Neuaufbau-Lauf 3 ist bereits aktiv"})
    r = await env.post("/etl/rebuilds", json={"start_stage": "classify"})
    assert r.status_code == 409 and "bereits aktiv" in r.json()["detail"]
    env.fake.reject["POST /rebuilds/3/pause"] = (409, {"error": "conflict", "detail": "Lauf 3 ist abgebrochen"})
    r = await env.post("/etl/rebuilds/3/pause")
    assert r.status_code == 409 and r.json()["detail"] == "Lauf 3 ist abgebrochen"
    assert (await env.post("/etl/rebuilds", json={"start_stage": "Bad!"})).status_code == 422


async def test_control_and_lists(env):
    """AK-25–28, AK-33: actions and lists are passed through."""
    for action, status in (("pause", "paused"), ("resume", "running"), ("cancel", "cancelled")):
        r = await env.post(f"/etl/rebuilds/5/{action}")
        assert r.status_code == 200 and r.json()["status"] == status
    assert (await env.post("/etl/rebuilds/5/explode")).status_code == 422
    assert (await env.get("/etl/rebuilds/5/errors")).json()["total"] == 2
    assert (await env.post("/etl/reconcile")).status_code == 202
    assert (await env.post("/etl/reconcile/full-rehash")).status_code == 202
    assert ("POST", "/reconcile/full-rehash", None) in env.fake.calls
    env.fake.results = [_result(4)]
    assert (await env.get("/etl/reconcile/results/4")).json()["id"] == 4
    assert (await env.get("/etl/reconcile/results/4/gaps", level=2)).json()["level"] == 2


async def test_state_with_progress_and_reconcile(env):
    """AK-23/AK-30/AK-34/AK-36: run, percent, last finished result, running reconciliation."""
    env.fake.run = {"id": 9, "status": "running", "in_run": 100, "finished": 63}
    env.fake.results = [{"id": 11, "state": "running", "started_at": datetime.now(timezone.utc).isoformat()},
                        _result(10, hours=2)]
    env.fake.reconciliation_running = 11
    st = (await env.get("/etl/state")).json()
    assert st["services"] == {"register": True, "rebuild": True}
    assert st["rebuild"]["percent"] == 63 and st["rebuild"]["run"]["id"] == 9
    assert st["reconcile"]["last"]["id"] == 10 and st["reconcile"]["running"] == 11
    assert st["reconcile"]["attention"] is False and st["light"] == "green"


async def test_rebuild_service_down(env):
    """EC-9/AK-41: PROJ-120 down → matrix and counts still there, rebuild/reconcile marked unavailable."""
    await env.source(1, states={"classify": "failed_permanent"})
    env.fake.down = True
    st = (await env.get("/etl/state")).json()
    assert st["services"] == {"register": True, "rebuild": False}
    assert st["rebuild"] is None and st["reconcile"] is None
    assert st["matrix"]["classify"]["failed_permanent"] == 1
    r = await env.post("/etl/rebuilds", json={"start_stage": "classify"})
    assert r.status_code == 503 and r.json()["service"] == "rebuild"
    assert (await env.get("/etl/errors")).json()["total"] == 1


async def test_no_run_yet(env):
    st = (await env.get("/etl/state")).json()
    assert st["rebuild"] == {"run": None, "active": False, "percent": None}
    assert st["reconcile"]["last"] is None and st["light"] == "red"
