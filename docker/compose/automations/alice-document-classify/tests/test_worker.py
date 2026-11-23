"""Work loop against the fake register (AK-6, AK-41, AK-42, AK-44, AK-45, EC-15)."""
import asyncio

from app.worker import Worker

from .conftest import drain


def make(settings, registry, classifier, **kw):
    for k, v in kw.items():
        setattr(settings, k, v)
    return Worker(settings, registry, classifier)


async def test_concurrency_one(settings, registry, classifier):  # AK-41
    for i in range(5):
        registry.add(f"src{i:09d}")
    w = make(settings, registry, classifier)
    await drain(w)
    assert registry.max_running == 1
    assert all(s == "done" for s in registry.state.values())
    assert [c[1] for c in registry.calls if c[0] == "claim" and c[2]] == [1] * 5


async def test_concurrency_configurable(settings, registry, classifier):
    for i in range(5):
        registry.add(f"src{i:09d}")
    w = make(settings, registry, classifier, concurrency=3)
    await drain(w)
    assert registry.max_running == 3


async def test_done_writes_once(settings, registry, classifier):  # AK-1, AK-45
    registry.add("srcaaaaaaaaa")
    await drain(make(settings, registry, classifier))
    writes = [c for c in registry.calls if c[0] == "write"]
    assert len(writes) == 1 and registry.state["srcaaaaaaaaa"] == "done"
    fields = registry.written["srcaaaaaaaaa"]["fields"]
    assert set(fields) == {"type", "classification", "title", "summary", "summary_language_uncertain", "fields"}
    assert registry.written["srcaaaaaaaaa"]["token"]  # write carries the claim token


async def test_batch_flag(settings, registry, classifier):
    registry.add("srcaaaaaaaaa")
    await drain(make(settings, registry, classifier, batch=True))
    assert registry.written["srcaaaaaaaaa"]["batch"] is True


async def test_gateway_down_releases_and_continues(settings, registry, classifier, gateway, caplog):  # AK-42
    registry.add("srcaaaaaaaaa")
    gateway.down = True
    w = make(settings, registry, classifier, llm_retry_seconds=0.05)
    await w.step()
    await w.wait_idle()
    assert ("release", "srcaaaaaaaaa", 0) in registry.calls
    assert not [c for c in registry.calls if c[0] in ("fail", "write")]  # no failed attempt
    assert "LLM gateway unavailable" in caplog.text
    errors, warnings = w.health()
    assert not errors and any("LLM nicht verfügbar" in x for x in warnings)
    registry.queue.append("srcaaaaaaaaa")  # the register hands it out again
    assert await w.step() == 0  # paused
    gateway.down = False
    await asyncio.sleep(0.06)
    await drain(w)
    assert registry.state["srcaaaaaaaaa"] == "done"


async def test_key_rejected_unhealthy(settings, registry, classifier, gateway):
    registry.add("srcaaaaaaaaa")
    gateway.status = 401
    w = make(settings, registry, classifier)
    await w.step()
    await w.wait_idle()
    errors, _ = w.health()
    assert any("Schlüssel" in e for e in errors)


async def test_invalid_answer_fails(settings, registry, classifier, gateway):  # AK-44
    registry.add("srcaaaaaaaaa")
    gateway.push("classify", "x", "y")
    await drain(make(settings, registry, classifier))
    fail = [c for c in registry.calls if c[0] == "fail"]
    assert fail and fail[0][3] is False and "Ungültige Antwort des LLM (Klassifizierung" in fail[0][2]
    assert "srcaaaaaaaaa" not in registry.written  # frontmatter unchanged


async def test_manual_unknown_type_permanent(settings, registry, classifier):
    registry.add("srcaaaaaaaaa", type="Quittung", manual=["type"])
    await drain(make(settings, registry, classifier))
    assert registry.state["srcaaaaaaaaa"] == "failed_permanent"


async def test_discarded_result_released(settings, registry, classifier):  # EC-15
    registry.add("srcaaaaaaaaa")
    registry.discard = True
    await drain(make(settings, registry, classifier))
    assert registry.state["srcaaaaaaaaa"] == "pending"
    assert not [c for c in registry.calls if c[0] in ("fail", "done")]


async def test_registry_down(settings, registry, classifier):
    registry.unavailable = True
    w = make(settings, registry, classifier)
    await w.step()
    errors, _ = w.health()
    assert any("Register nicht erreichbar" in e for e in errors)
    registry.unavailable = False
    await w.step()
    assert w.health() == ([], [])


async def test_cancel_writes_nothing(settings, registry, classifier, gateway):  # AK-45
    registry.add("srcaaaaaaaaa")
    started = asyncio.Event()

    def slow(req):
        started.set()
        return {"type": "Invoice", "confidence": 0.9}

    gateway.push("classify", slow)
    orig = classifier.llm.chat

    async def chat(*a, **kw):
        res = await orig(*a, **kw)
        await asyncio.sleep(10)
        return res

    classifier.llm.chat = chat
    w = make(settings, registry, classifier)
    await w.step()
    await started.wait()
    await w.stop()
    assert not [c for c in registry.calls if c[0] in ("write", "done", "fail")]
