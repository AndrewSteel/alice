"""PROJ-83 — integration-ish tests for execute_ha_intents() value handling.

Uses a fake httpx-like async client (conftest stubs the real httpx module).
"""
import asyncio

import pytest

import app.ha_path as ha_path
from app.ha_path import IntentMatch, execute_ha_intents


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json


class FakeClient:
    """Records POSTs; answers GET /api/states/<entity> from `states`."""

    def __init__(self, states=None, post_status=200):
        self.states = states or {}
        self.post_status = post_status
        self.posts = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json})
        return _Resp(self.post_status)

    async def get(self, url, headers=None, timeout=None):
        entity = url.rsplit("/", 1)[-1]
        if entity in self.states:
            return _Resp(200, {"attributes": self.states[entity]})
        return _Resp(404)


@pytest.fixture(autouse=True)
def _ha_token(monkeypatch):
    monkeypatch.setattr(ha_path, "HA_TOKEN", "test-token")
    monkeypatch.setattr(ha_path, "HA_URL", "http://ha.test")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Percent values — light / cover
# ---------------------------------------------------------------------------
def test_cover_exact_position():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="cover.buro",
                         domain="cover", service="cover.set_cover_position",
                         parameters={"position": 50})
    client = FakeClient()
    text, results = run(execute_ha_intents(
        [intent], client, parts=["Rolladen im Büro auf 37 Prozent stellen"]))
    assert client.posts[0]["json"]["position"] == 37
    assert results[0]["success"] is True
    assert "37 Prozent" in text


def test_light_exact_brightness():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="light.wohnzimmer",
                         domain="light", service="light.turn_on",
                         parameters={"brightness_pct": 100})
    client = FakeClient()
    text, results = run(execute_ha_intents(
        [intent], client, parts=["Licht im Wohnzimmer auf 30 Prozent dimmen"]))
    assert client.posts[0]["json"]["brightness_pct"] == 30
    assert "30 Prozent" in text


def test_percent_boundary_values_allowed():
    for val, spoken in [(0, "auf 0 Prozent"), (100, "auf 100 Prozent")]:
        intent = IntentMatch(matched=True, certainty=0.9, entity_id="cover.buro",
                             domain="cover", service="cover.set_cover_position",
                             parameters={"position": 50})
        client = FakeClient()
        _, results = run(execute_ha_intents([intent], client, parts=[spoken]))
        assert results[0]["success"] is True
        assert client.posts[0]["json"]["position"] == val


def test_percent_out_of_range_not_executed():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="cover.buro",
                         domain="cover", service="cover.set_cover_position",
                         parameters={"position": 50})
    client = FakeClient()
    text, results = run(execute_ha_intents(
        [intent], client, parts=["Rolladen auf 150 Prozent"]))
    assert client.posts == []          # no HA call
    assert results[0]["success"] is False
    assert "zwischen 0 und 100 Prozent" in text


# ---------------------------------------------------------------------------
# Temperature — dynamic bounds
# ---------------------------------------------------------------------------
def test_temperature_within_dynamic_range():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="climate.ht_buro",
                         domain="climate", service="climate.set_temperature",
                         parameters={"temperature": 20})
    client = FakeClient(states={"climate.ht_buro": {"min_temp": 5, "max_temp": 30}})
    text, results = run(execute_ha_intents(
        [intent], client, parts=["Heizung im Büro auf 21 Grad stellen"]))
    assert client.posts[0]["json"]["temperature"] == 21
    assert "21 Grad" in text


def test_temperature_out_of_range_uses_actual_bounds():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="climate.ht_buro",
                         domain="climate", service="climate.set_temperature",
                         parameters={"temperature": 20})
    client = FakeClient(states={"climate.ht_buro": {"min_temp": 5, "max_temp": 30}})
    text, results = run(execute_ha_intents(
        [intent], client, parts=["Heizung im Büro auf 45 Grad stellen"]))
    assert client.posts == []
    assert "zwischen 5 und 30 Grad" in text


def test_friendly_name_used_in_messages_when_available(monkeypatch):
    # PROJ-83 BUG-3 — range/success message uses the HA friendly name, not the
    # entity_id slug ("HT Büro", not "Ht buro").
    class _FN:
        async def fetch(self, *a, **kw):
            return [{"entity_id": "climate.ht_buro", "friendly_name": "HT Büro"}]

    import app.memory as memory
    monkeypatch.setattr(memory, "pool", lambda: _FN())

    intent = IntentMatch(matched=True, certainty=0.9, entity_id="climate.ht_buro",
                         domain="climate", service="climate.set_temperature",
                         parameters={"temperature": 20})
    client = FakeClient(states={"climate.ht_buro": {"min_temp": 5, "max_temp": 30}})
    text, _ = run(execute_ha_intents([intent], client, parts=["auf 45 Grad"]))
    assert text.startswith("HT Büro lässt sich nur")

    client2 = FakeClient(states={"climate.ht_buro": {"min_temp": 5, "max_temp": 30}})
    text2, _ = run(execute_ha_intents([intent], client2, parts=["auf 21 Grad"]))
    assert text2 == "HT Büro auf 21 Grad gestellt."


def test_entity_id_slug_fallback_when_no_friendly_name(monkeypatch):
    class _Empty:
        async def fetch(self, *a, **kw):
            return []

    import app.memory as memory
    monkeypatch.setattr(memory, "pool", lambda: _Empty())

    intent = IntentMatch(matched=True, certainty=0.9, entity_id="cover.buro",
                         domain="cover", service="cover.set_cover_position",
                         parameters={"position": 50})
    client = FakeClient()
    text, _ = run(execute_ha_intents([intent], client, parts=["auf 150 Prozent"]))
    assert text.startswith("Buro lässt sich nur")


def test_temperature_decimal_rounded():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="climate.ht_buro",
                         domain="climate", service="climate.set_temperature",
                         parameters={"temperature": 20})
    client = FakeClient(states={"climate.ht_buro": {"min_temp": 5, "max_temp": 30}})
    run(execute_ha_intents([intent], client, parts=["Heizung auf 21,5 Grad"]))
    assert client.posts[0]["json"]["temperature"] == 22


def test_temperature_bounds_unavailable_accepts_value():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="climate.unknown",
                         domain="climate", service="climate.set_temperature",
                         parameters={"temperature": 20})
    client = FakeClient(states={})   # GET returns 404
    _, results = run(execute_ha_intents([intent], client, parts=["auf 21 Grad"]))
    assert results[0]["success"] is True
    assert client.posts[0]["json"]["temperature"] == 21


# ---------------------------------------------------------------------------
# Missing number -> abort HA_FAST
# ---------------------------------------------------------------------------
def test_missing_number_raises_for_llm_fallback():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="cover.buro",
                         domain="cover", service="cover.set_cover_position",
                         parameters={"position": 50})
    client = FakeClient()
    with pytest.raises(ValueError):
        run(execute_ha_intents([intent], client, parts=["Rolladen auf stellen"]))
    assert client.posts == []


# ---------------------------------------------------------------------------
# Multi-command — independent values
# ---------------------------------------------------------------------------
def test_multi_command_independent_values():
    i1 = IntentMatch(matched=True, certainty=0.9, entity_id="cover.buro",
                     domain="cover", service="cover.set_cover_position",
                     parameters={"position": 50})
    i2 = IntentMatch(matched=True, certainty=0.9, entity_id="light.wohnzimmer",
                     domain="light", service="light.turn_on",
                     parameters={"brightness_pct": 50})
    client = FakeClient()
    text, results = run(execute_ha_intents(
        [i1, i2], client, parts=["Rolladen auf 50", "Licht auf 30 Prozent"]))
    assert client.posts[0]["json"]["position"] == 50
    assert client.posts[1]["json"]["brightness_pct"] == 30


def test_temperature_exact_min_and_max_allowed():
    for spoken, expected in [("auf 5 Grad", 5), ("auf 30 Grad", 30)]:
        intent = IntentMatch(matched=True, certainty=0.9, entity_id="climate.ht_buro",
                             domain="climate", service="climate.set_temperature",
                             parameters={"temperature": 20})
        client = FakeClient(states={"climate.ht_buro": {"min_temp": 5, "max_temp": 30}})
        _, results = run(execute_ha_intents([intent], client, parts=[spoken]))
        assert results[0]["success"] is True
        assert client.posts[0]["json"]["temperature"] == expected


def test_leading_zeros_in_execute():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="light.wz",
                         domain="light", service="light.turn_on",
                         parameters={"brightness_pct": 50})
    client = FakeClient()
    run(execute_ha_intents([intent], client, parts=["Licht auf 050 Prozent"]))
    assert client.posts[0]["json"]["brightness_pct"] == 50


def test_entity_offline_error_is_friendly():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="cover.buro",
                         domain="cover", service="cover.set_cover_position",
                         parameters={"position": 50})
    client = FakeClient(post_status=500)
    text, results = run(execute_ha_intents([intent], client, parts=["Rolladen auf 40 Prozent"]))
    assert results[0]["success"] is False
    assert "HTTP 500" in text or "Fehler" in text


# ---------------------------------------------------------------------------
# Shopping list
# ---------------------------------------------------------------------------
class _FakePool:
    def __init__(self, row):
        self._row = row

    async def fetchrow(self, *args, **kwargs):
        return self._row


def _patch_pool(monkeypatch, row):
    import app.memory as memory
    monkeypatch.setattr(memory, "pool", lambda: _FakePool(row))


def test_shopping_list_add_item(monkeypatch):
    _patch_pool(monkeypatch, {"entity_id": "todo.einkaufsliste"})
    shop_intent = IntentMatch(matched=True, certainty=1.0, domain="todo")
    client = FakeClient()
    text, results = run(execute_ha_intents(
        [shop_intent], client,
        parts=["2 Packungen Milch zur Einkaufsliste hinzufügen"],
        shopping_items=["2 Packungen Milch"]))
    assert client.posts[0]["url"].endswith("/api/services/todo/add_item")
    assert client.posts[0]["json"] == {"entity_id": "todo.einkaufsliste", "item": "2 Packungen Milch"}
    assert results[0]["success"] is True


def test_shopping_list_very_long_item_not_truncated(monkeypatch):
    _patch_pool(monkeypatch, {"entity_id": "todo.einkaufsliste"})
    shop_intent = IntentMatch(matched=True, certainty=1.0, domain="todo")
    client = FakeClient()
    long_item = "einen großen Sack Bio-Kartoffeln festkochend für das Wochenende"
    run(execute_ha_intents(
        [shop_intent], client, parts=[long_item + " zur Einkaufsliste hinzufügen"],
        shopping_items=[long_item]))
    assert client.posts[0]["json"]["item"] == long_item


def test_shopping_list_duplicate_still_added(monkeypatch):
    # No dedup — follows HA default behaviour.
    _patch_pool(monkeypatch, {"entity_id": "todo.einkaufsliste"})
    shop_intent = IntentMatch(matched=True, certainty=1.0, domain="todo")
    client = FakeClient()
    _, results = run(execute_ha_intents(
        [shop_intent], client, parts=["Milch zur Einkaufsliste"], shopping_items=["Milch"]))
    assert results[0]["success"] is True


def test_shopping_list_no_list_configured(monkeypatch):
    _patch_pool(monkeypatch, None)
    shop_intent = IntentMatch(matched=True, certainty=1.0, domain="todo")
    client = FakeClient()
    text, results = run(execute_ha_intents(
        [shop_intent], client, parts=["Milch zur Einkaufsliste"],
        shopping_items=["Milch"]))
    assert client.posts == []
    assert "keine Einkaufsliste" in text


# ---------------------------------------------------------------------------
# Non-value intent — no regression
# ---------------------------------------------------------------------------
def test_valueless_intent_unchanged():
    intent = IntentMatch(matched=True, certainty=0.9, entity_id="light.wohnzimmer",
                         domain="light", service="light.turn_on", parameters={})
    client = FakeClient()
    text, results = run(execute_ha_intents(
        [intent], client, parts=["Licht im Wohnzimmer einschalten"]))
    assert results[0]["success"] is True
    assert "eingeschaltet" in text
    assert "brightness_pct" not in client.posts[0]["json"]
