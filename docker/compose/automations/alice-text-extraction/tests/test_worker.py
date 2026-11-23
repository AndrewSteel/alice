"""Work loop against a fake register: flow, errors, NAS, parallelism, heartbeat, health, interface."""
import asyncio
import os
import pathlib
import shutil

import pytest

from app.extractor import Extractor
from app.worker import Worker

from .conftest import FakeOcr, FakeRegistry, drain, make_pdf, write
from .test_formats import DE, EN

ROOT = pathlib.Path(__file__).resolve().parents[5]


def worker(settings, registry, extractor):
    return Worker(settings, registry, extractor)


async def test_flow_done(settings, registry, extractor, nas):  # AK-1, AK-17, AK-18
    path = make_pdf(nas / "share" / "a.pdf", [DE, EN])
    registry.add("src000000001", [path], "a.pdf")
    w = worker(settings, registry, extractor)
    await drain(w)
    assert registry.state["src000000001"] == "done"
    wr = registry.written["src000000001"]
    assert wr["fields"]["extraction"] == {"method": "text", "ocr_pages": [], "empty": False}
    assert wr["fields"]["language"] == "de"
    assert set(wr["fields"]) == {"extraction", "language"}  # no state, error or counter (AK-17)
    assert "## Seite 1" in wr["content"] and "## Seite 2" in wr["content"]
    assert wr["batch"] is False
    assert registry.claim_kinds and all(k == ["document"] for k in registry.claim_kinds)  # AK-3
    order = [c[0] for c in registry.calls if c[0] != "claim"]
    assert order == ["write", "done"]


async def test_batch_mode(settings, registry, extractor, nas):  # AK-2 (mass run)
    settings.batch = True
    registry.add("src000000001", [write(nas / "share" / "a.txt", "Hallo")])
    await drain(worker(settings, registry, extractor))
    assert registry.written["src000000001"]["batch"] is True


async def test_second_location_used(settings, registry, extractor, nas):  # EC-8
    path = write(nas / "share" / "b.txt", "Inhalt")
    registry.add("src000000001", [str(nas / "share" / "gone.txt"), path])
    await drain(worker(settings, registry, extractor))
    assert registry.state["src000000001"] == "done"


async def test_empty_result(settings, registry, extractor, nas):  # AK-20
    path = make_pdf(nas / "share" / "leer.pdf", [None, None])
    registry.add("src000000001", [path])
    await drain(worker(settings, registry, extractor))
    wr = registry.written["src000000001"]
    assert registry.state["src000000001"] == "done"
    assert wr["fields"]["extraction"]["empty"] is True and wr["fields"]["language"] is None
    assert wr["content"].startswith("Kein Text extrahiert")
    assert f"[leer.pdf](<{path}>)" in wr["content"]


async def test_permanent_error(settings, registry, extractor, nas):  # AK-21, AK-22
    path = make_pdf(nas / "share" / "secret.pdf", [DE], password="pw")
    registry.add("src000000001", [path])
    await drain(worker(settings, registry, extractor))
    fail = [c for c in registry.calls if c[0] == "fail"]
    assert fail == [("fail", "src000000001", "PDF ist passwortgeschützt", True)]
    assert "src000000001" not in registry.written
    assert str(nas) not in fail[0][2]


async def test_content_group_logged_with_source_id(settings, registry, ocr, nas, caplog):
    from .test_formats import fake_converter, make_ods_zip, make_xlsx

    factory, calls = fake_converter({"xlsx": make_xlsx(nas / "conv.xlsx")})
    path = make_ods_zip(nas / "share" / "terrasse.odt", "application/vnd.oasis.opendocument.spreadsheet")
    registry.add("src000000007", [path])
    await drain(worker(settings, registry, Extractor(settings, ocr=ocr, converter_factory=factory)))
    assert registry.state["src000000007"] == "done" and calls[0][1] == "xlsx"
    assert "## Blatt Umsätze" in registry.written["src000000007"]["content"]
    assert ("Source src000000007: content is a sheet document although the extension is .odt; "
            "extracting as sheet") in caplog.text
    assert str(nas) not in caplog.text


async def test_transient_error(settings, registry, nas):  # AK-23
    path = make_pdf(nas / "share" / "scan.pdf", [("scan",)])
    registry.add("src000000001", [path])
    w = worker(settings, registry, Extractor(settings, ocr=FakeOcr(fail_on=1)))
    await drain(w)
    fail = [c for c in registry.calls if c[0] == "fail"][0]
    assert fail[3] is False and "Zeitüberschreitung" in fail[2]
    assert "src000000001" not in registry.written


async def test_unexpected_error_is_transient(settings, registry, nas):
    class Boom:
        def extract(self, path, progress=None):
            raise MemoryError()

    registry.add("src000000001", [write(nas / "share" / "a.txt", "x")])
    await drain(worker(settings, registry, Boom()))
    fail = [c for c in registry.calls if c[0] == "fail"][0]
    assert fail[3] is False and "MemoryError" in fail[2]


async def test_nas_unavailable(settings, registry, extractor, nas, caplog):  # AK-24
    path = write(nas / "share" / "a.txt", "Inhalt")
    registry.add("src000000001", [path])
    shutil.move(nas / "share", nas / "away")
    (nas / "share").mkdir()  # empty mount point: share not mounted
    w = worker(settings, registry, extractor)
    await w.step()
    await w.wait_idle()
    assert ("release", "src000000001", 0) in registry.calls
    assert not [c for c in registry.calls if c[0] == "fail"]
    assert "NAS share" in caplog.text
    _, warnings = w.health()
    assert any("NAS nicht erreichbar" in x for x in warnings)
    # paused: no new claims while the share is away
    claims = len([c for c in registry.calls if c[0] == "claim"])
    registry.add("src000000002", [path])
    await w.step()
    assert len([c for c in registry.calls if c[0] == "claim"]) == claims
    # share back → continues without intervention
    (nas / "share").rmdir()
    shutil.move(nas / "away", nas / "share")
    w.nas_paused_until = 0
    registry.queue.insert(0, "src000000001")
    await drain(w)
    assert registry.state["src000000001"] == "done" and registry.state["src000000002"] == "done"


async def test_missing_file(settings, registry, extractor, nas):  # AK-25, EC-9
    registry.add("src000000001", [str(nas / "share" / "weg.pdf")])
    w = worker(settings, registry, extractor)
    await drain(w)
    assert ("release", "src000000001", 3600) in registry.calls
    assert not [c for c in registry.calls if c[0] == "fail"]
    assert w.nas_paused_until == 0


async def test_deleted_while_reading(settings, registry, nas):  # EC-9
    path = write(nas / "share" / "a.txt", "x")

    class Vanish:
        def extract(self, p, progress=None):
            os.remove(p)
            raise FileNotFoundError(p)

    registry.add("src000000001", [path])
    await drain(worker(settings, registry, Vanish()))
    assert ("release", "src000000001", 3600) in registry.calls


async def test_concurrency_limit(settings, registry, nas):  # AK-32
    settings.concurrency = 2
    for i in range(10):
        registry.add(f"src{i:09d}", [make_pdf(nas / "share" / f"s{i}.pdf", [("scan",)])])
    ext = Extractor(settings, ocr=FakeOcr(delay=0.05))
    w = worker(settings, registry, ext)
    await drain(w, rounds=2000)
    assert all(s == "done" for s in registry.state.values())
    assert registry.max_running == 2
    assert all(c[1] <= 2 for c in registry.calls if c[0] == "claim")


async def test_heartbeat_during_long_extraction(settings, registry, nas):  # AK-33
    settings.heartbeat_seconds = 0.02
    path = make_pdf(nas / "share" / "lang.pdf", [("scan",)] * 20)
    registry.add("src000000001", [path])
    w = worker(settings, registry, Extractor(settings, ocr=FakeOcr(delay=0.01)))
    await drain(w)
    beats = [c for c in registry.calls if c[0] == "heartbeat"]
    assert len(beats) >= 3 and registry.state["src000000001"] == "done"
    assert registry.written["src000000001"]["fields"]["extraction"]["ocr_pages"] == list(range(1, 21))


async def test_stop_writes_nothing(settings, registry, nas):  # AK-34
    path = make_pdf(nas / "share" / "lang.pdf", [("scan",)] * 50)
    registry.add("src000000001", [path])
    w = worker(settings, registry, Extractor(settings, ocr=FakeOcr(delay=0.02)))
    await w.step()
    await asyncio.sleep(0.1)
    await w.stop()
    assert not [c for c in registry.calls if c[0] in ("write", "done")]
    assert registry.state["src000000001"] == "running"  # taken back by the register's timeout


async def test_registry_unavailable(settings, registry, extractor, nas, caplog):  # AK-35
    registry.unavailable = True
    w = worker(settings, registry, extractor)
    await w.step()
    errors, _ = w.health()
    assert errors and "Register nicht erreichbar" in errors[0] and "ConnectError" in errors[0]
    assert "Source register unavailable" in caplog.text
    registry.unavailable = False
    registry.add("src000000001", [write(nas / "share" / "a.txt", "Hallo")])
    await drain(w)
    assert w.health() == ([], []) and registry.state["src000000001"] == "done"


async def test_registry_grace(settings, registry, extractor):
    settings.registry_grace_seconds = 3600
    registry.unavailable = True
    w = worker(settings, registry, extractor)
    await w.step()
    errors, warnings = w.health()
    assert errors == [] and "Register nicht erreichbar" in warnings[0]


async def test_locked_markdown_released(settings, registry, extractor, nas):
    from app.registry import RegistryConflict

    async def locked(*a, **kw):
        raise RegistryConflict('{"error": "locked"}')

    registry.write = locked
    registry.add("src000000001", [write(nas / "share" / "a.txt", "Hallo")])
    await drain(worker(settings, registry, extractor))
    assert ("release", "src000000001", 0) in registry.calls
    assert not [c for c in registry.calls if c[0] == "fail"]


# ---------------------------------------------------------------- service rules
def test_no_nginx_route():  # AK-36
    nginx = ROOT / "docker" / "compose" / "infra" / "nginx"
    assert nginx.is_dir()
    for f in nginx.rglob("*"):
        if f.is_file():
            text = f.read_text(errors="ignore")
            assert "alice-text-extraction" not in text and ":8014" not in text, f


def test_no_old_system_channels():  # AK-37: no MQTT, no Redis, no LLM gateway
    svc = pathlib.Path(__file__).resolve().parents[1]
    reqs = (svc / "requirements.txt").read_text().lower()
    assert "paho" not in reqs and "redis" not in reqs
    for f in (svc / "app").rglob("*.py"):
        code = [line for line in f.read_text().lower().splitlines() if "import" in line or "://" in line]
        for word in ("mqtt", "paho", "redis", "llm-gateway", "llm_gateway", "dms:"):
            assert not [line for line in code if word in line], (f, word)


def test_http_health_unhealthy_without_registry(monkeypatch):  # AK-35 via the interface
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("REGISTRY_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EXTRACT_REGISTRY_GRACE_SECONDS", "0")
    monkeypatch.setenv("EXTRACT_POLL_SECONDS", "0.05")
    with TestClient(app) as c:
        for _ in range(100):
            h = c.get("/health")
            if h.status_code == 503:
                break
            import time

            time.sleep(0.05)
        assert h.status_code == 503 and h.json()["status"] == "unhealthy"
        assert "Register nicht erreichbar" in h.json()["errors"][0]
        s = c.get("/status").json()
        assert s["concurrency"] == 2 and s["active"] == []
