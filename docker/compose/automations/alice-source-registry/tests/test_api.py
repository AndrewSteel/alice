"""HTTP interface (FastAPI TestClient with lifespan) and the no-nginx-route rule (AK-30, AK-33)."""
import pathlib

import pytest

from .conftest import DSN

ROOT = pathlib.Path(__file__).resolve().parents[5]


def test_no_nginx_route():  # AK-33
    nginx = ROOT / "docker" / "compose" / "infra" / "nginx"
    assert nginx.is_dir()
    for f in nginx.rglob("*"):
        if f.is_file():
            text = f.read_text(errors="ignore")
            assert "alice-source-registry" not in text and ":8012" not in text, f


@pytest.fixture
def client(pool, repo_dir, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("POSTGRES_DSN", DSN)
    monkeypatch.setenv("SOT_REPO_PATH", str(repo_dir))
    monkeypatch.delenv("REDIS_HOST", raising=False)
    with TestClient(app) as c:
        yield c


def test_http_flow(client):
    h = client.get("/health")
    assert h.status_code == 200 and h.json()["status"] == "healthy"
    r = client.post("/sources", json={"kind": "document", "hash": "sha256:" + "e" * 16, "title": "scan.pdf",
                                      "location": {"path": "/nas/scan.pdf"}, "captured": "2026-11-05T10:00:00Z"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert client.get("/sources", params={"hash": "sha256:" + "e" * 16}).json()["id"] == sid
    doc = client.get(f"/sources/{sid}/document").json()
    assert doc["frontmatter"]["title"] == "scan.pdf"
    claim = client.post("/stages/extract/claim", json={"limit": 5}).json()
    item = next(i for i in claim["items"] if i["source_id"] == sid)
    w = client.put(f"/sources/{sid}/document", json={"stage": "extract", "content": "Text",
                                                      "fields": {"language": "de"}})
    assert w.status_code == 200 and w.json()["changed"]
    f = client.post(f"/sources/{sid}/stages/extract/fail", json={"token": item["token"], "error": "kaputt"})
    assert f.json()["state"] == "failed" and f.json()["attempts"] == 1
    assert client.post(f"/sources/{sid}/stages/extract/retry").json() == {"state": "pending", "attempts": 0}
    assert any(s["name"] == "thumbnail" for s in client.get("/stages").json()["stages"])


def test_validation_and_errors(client):
    bad = client.post("/sources", json={"kind": "spreadsheet", "hash": "sha256:" + "e" * 16, "title": "x",
                                        "location": {"path": "/x"}})
    assert bad.status_code == 422
    both = client.post("/sources", json={"kind": "document", "hash": "sha256:" + "e" * 16, "title": "x",
                                         "location": {"path": "/x", "mailbox": "m", "message_id": "1"}})
    assert both.status_code == 422
    assert client.get("/sources/zzzzzzzzzzzz").status_code == 404
    r = client.post("/sources", json={"kind": "document", "hash": "sha256:" + "f" * 16, "title": "x",
                                      "location": {"path": "/x"}})
    sid = r.json()["id"]
    prot = client.put(f"/sources/{sid}/document", json={"stage": "extract", "fields": {"id": "x"}})
    assert prot.status_code == 422


def test_unhealthy_without_repo(client, repo_dir):  # AK-30
    repo_dir.rename(repo_dir.parent / "gone")
    client.app.state.reg._set_available(False, "Repo-Ordner nicht erreichbar")
    h = client.get("/health")
    assert h.status_code == 503 and h.json()["status"] == "unhealthy"
    assert any("nicht erreichbar" in r for r in h.json()["reasons"])
    w = client.post("/sources", json={"kind": "document", "hash": "sha256:" + "g" * 16, "title": "x",
                                      "location": {"path": "/x"}})
    assert w.status_code == 503 and w.json()["error"] == "repo_unavailable"
    assert client.post("/stages/extract/claim").json()["paused"] is True


def test_http_extract_interface(client):  # PROJ-117: kinds, permanent, heartbeat, delayed release
    r = client.post("/sources", json={"kind": "document", "hash": "sha256:" + "h" * 16, "title": "a.pdf",
                                      "location": {"path": "/nas/a.pdf"}})
    sid = r.json()["id"]
    assert client.post("/stages/extract/claim", json={"kinds": ["spreadsheet"]}).status_code == 422
    item = client.post("/stages/extract/claim", json={"limit": 5, "kinds": ["document"]}).json()["items"][0]
    assert item["source_id"] == sid and item["kind"] == "document"
    hb = client.post(f"/sources/{sid}/stages/extract/heartbeat", json={"token": item["token"]})
    assert hb.status_code == 200 and hb.json()["state"] == "running"
    rel = client.post(f"/sources/{sid}/stages/extract/release", json={"token": item["token"], "delay_seconds": 60})
    assert rel.status_code == 200 and rel.json()["next_retry_at"]
    client.post(f"/sources/{sid}/stages/extract/retry")
    item = client.post("/stages/extract/claim", json={"kinds": ["document"]}).json()["items"][0]
    f = client.post(f"/sources/{sid}/stages/extract/fail",
                    json={"token": item["token"], "error": "PDF ist passwortgeschützt", "permanent": True})
    assert f.json()["state"] == "failed_permanent"
