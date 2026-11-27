"""Worker behaviour without a database: register unreachable, health, PostgreSQL away."""
import httpx

from app.registry import RegistryClient
from app.worker import Describer, Locator, next_midnight

from .conftest import FakeStore


def down_registry() -> RegistryClient:
    def handler(request):
        raise httpx.ConnectError("register down", request=request)
    return RegistryClient("http://registry", client=httpx.AsyncClient(base_url="http://registry",
                                                                      transport=httpx.MockTransport(handler)))


async def test_register_unreachable_pauses_and_reports(settings, vision, geoapify, weaviate):  # AK-37
    reg = down_registry()
    d = Describer(settings, reg, FakeStore(), vision)
    loc = Locator(settings, reg, FakeStore(), weaviate, geoapify, d)
    assert await d.step() == 0 and await loc.step() == 0
    errors, _ = d.health()
    assert any("Register nicht erreichbar" in e for e in errors)  # grace 0 in the test settings
    assert any("Register nicht erreichbar" in e for e in loc.health()[0])


async def test_register_back_continues(settings, vision):  # AK-37
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json={"paused": False, "reason": None, "items": []})
    reg = RegistryClient("http://r", client=httpx.AsyncClient(base_url="http://r", transport=httpx.MockTransport(handler)))
    d = Describer(settings, reg, FakeStore(), vision)
    await d.step()
    assert d.health()[0]
    await d.step()
    assert d.health() == ([], [])


async def test_postgres_unreachable(settings, vision):
    store = FakeStore()
    store.down = True
    d = Describer(settings, down_registry(), store, vision)
    await d.step()
    assert any("PostgreSQL nicht erreichbar" in e for e in d.health()[0])


async def test_claim_order_and_lock(settings, vision):  # AK-31, AK-32, AK-33
    bodies = []

    def handler(request):
        import json
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"paused": False, "reason": None, "items": []})
    reg = RegistryClient("http://r", client=httpx.AsyncClient(base_url="http://r", transport=httpx.MockTransport(handler)))
    store = FakeStore()
    store.requests = ["aaaaaaaaaaaa"]
    d = Describer(settings, reg, store, vision)
    await d.step()
    assert [set(b) - {"limit", "kinds"} for b in bodies] == [{"source_ids"}, {"registered_since"}]
    assert all(b["kinds"] == ["image"] for b in bodies)
    settings.backlog_released = True
    bodies.clear()
    await d.step()
    assert [set(b) - {"limit", "kinds"} for b in bodies] == [{"registered_since"}, {"registered_before"}]


def test_next_midnight_berlin():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Berlin")
    assert next_midnight(datetime(2026, 3, 28, 23, 30, tzinfo=tz), "Europe/Berlin") == datetime(2026, 3, 29, tzinfo=tz)
