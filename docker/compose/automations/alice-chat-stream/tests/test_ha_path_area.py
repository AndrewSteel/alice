"""PROJ-84 — device-area context: precedence, multi-entity, room clarification."""
import asyncio

import pytest

import app.ha_path as ha_path
from app.ha_path import (
    AreaResolution,
    IntentMatch,
    decide_path,
    execute_ha_intents,
    parse_device_room,
)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# parse_device_room
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source,expected", [
    ("esphome:Büro", "Büro"),
    ("esphome:Wohnzimmer", "Wohnzimmer"),
    ("esphome:Wohn_zimmer", "Wohn zimmer"),
    ("esphome", None),
    ("webapp_cc", None),
    ("webapp_mic", None),
    (None, None),
    ("esphome:", None),
])
def test_parse_device_room(source, expected):
    assert parse_device_room(source) == expected


# ---------------------------------------------------------------------------
# Fake DB — one place to describe the house
# ---------------------------------------------------------------------------
class FakePool:
    def __init__(self, entities):
        # entities: list of dicts {entity_id, domain, friendly_name, aliases, area_name}
        self.entities = entities

    async def fetch(self, sql, *args):
        s = " ".join(sql.split())
        if "DISTINCT area_name" in s:
            seen = {e["area_name"] for e in self.entities if e.get("area_name")}
            return [{"area_name": a} for a in sorted(seen)]
        if "friendly_name, aliases" in s:
            return [
                {"entity_id": e["entity_id"], "friendly_name": e.get("friendly_name"),
                 "aliases": e.get("aliases", [])}
                for e in self.entities
            ]
        if "LOWER(area_name) = LOWER($1)" in s:
            area, domain = args
            return [
                {"entity_id": e["entity_id"]}
                for e in self.entities
                if (e.get("area_name") or "").lower() == area.lower()
                and e["domain"] == domain
            ]
        if "friendly_name IS NOT NULL" in s:  # _load_friendly_names
            ids = set(args[0])
            return [
                {"entity_id": e["entity_id"], "friendly_name": e["friendly_name"]}
                for e in self.entities
                if e["entity_id"] in ids and e.get("friendly_name")
            ]
        return []


HOUSE = [
    {"entity_id": "light.buero_decke", "domain": "light",
     "friendly_name": "Büro Deckenlicht", "area_name": "Büro"},
    {"entity_id": "light.buero_stehlampe", "domain": "light",
     "friendly_name": "Büro Stehlampe", "area_name": "Büro"},
    {"entity_id": "light.kueche_1", "domain": "light",
     "friendly_name": "Küche Spots", "area_name": "Küche"},
    {"entity_id": "cover.buero", "domain": "cover",
     "friendly_name": "Büro Rolladen", "area_name": "Büro"},
    {"entity_id": "light.wohnzimmer_lese", "domain": "light",
     "friendly_name": "Wohnzimmer Leselampe", "aliases": ["Leselampe"],
     "area_name": "Wohnzimmer"},
    {"entity_id": "climate.buero_ht", "domain": "climate",
     "friendly_name": "Büro Heizung", "area_name": "Büro"},
]


@pytest.fixture
def house(monkeypatch):
    import app.memory as memory
    pool = FakePool(HOUSE)
    monkeypatch.setattr(memory, "pool", lambda: pool)
    return pool


@pytest.fixture
def stub_lookup(monkeypatch):
    def _install(table):
        async def fake_lookup(part, client):
            for key, val in table.items():
                if key in part.lower():
                    return val
            return IntentMatch(matched=False, certainty=0.0)
        monkeypatch.setattr(ha_path, "lookup_intent", fake_lookup)
    return _install


@pytest.fixture(autouse=True)
def _ha_token(monkeypatch):
    monkeypatch.setattr(ha_path, "HA_TOKEN", "test-token")
    monkeypatch.setattr(ha_path, "HA_URL", "http://ha.test")


def _light_on():
    return IntentMatch(matched=True, certainty=0.9, entity_id="light.kueche_1",
                       domain="light", service="light.turn_on", parameters={})


class _Resp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, states=None, fail=None):
        self.states = states or {}
        self.fail = fail or set()   # entity_ids that return 500
        self.posts = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json})
        eid = (json or {}).get("entity_id")
        return _Resp(500 if eid in self.fail else 200)

    async def get(self, url, headers=None, timeout=None):
        entity = url.rsplit("/", 1)[-1]
        if entity in self.states:
            return _Resp(200, {"attributes": self.states[entity]})
        return _Resp(404)


# ---------------------------------------------------------------------------
# Precedence stage 3 — device room applied
# ---------------------------------------------------------------------------
def test_device_room_applies_to_all_domain_entities(house, stub_lookup):
    stub_lookup({"licht": _light_on()})
    d = run(decide_path("Licht einschalten", client=None, source="esphome:Büro"))
    assert d.path == "HA_FAST"
    at = d.area_targets[0]
    assert at.mode == "area"
    assert at.area == "Büro"
    assert set(at.entity_ids) == {"light.buero_decke", "light.buero_stehlampe"}

    client = FakeClient()
    text, results = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert len(client.posts) == 2
    assert text == "Licht im Büro eingeschaltet."
    assert all(r["success"] for r in results)


# ---------------------------------------------------------------------------
# Precedence stage 2 — named room beats device room
# ---------------------------------------------------------------------------
def test_named_room_beats_device_room(house, stub_lookup):
    stub_lookup({"licht": _light_on()})
    d = run(decide_path("Licht in der Küche einschalten", client=None,
                        source="esphome:Büro"))
    at = d.area_targets[0]
    assert at.mode == "area"
    assert at.area == "Küche"
    assert at.entity_ids == ["light.kueche_1"]


# ---------------------------------------------------------------------------
# Precedence stage 1 — named device wins, single entity
# ---------------------------------------------------------------------------
def test_named_device_wins(house, stub_lookup):
    stub_lookup({"leselampe": IntentMatch(
        matched=True, certainty=0.9, entity_id="light.wohnzimmer_lese",
        domain="light", service="light.turn_on", parameters={})})
    d = run(decide_path("Leselampe einschalten", client=None, source="esphome:Büro"))
    at = d.area_targets[0]
    assert at.mode == "entity"

    client = FakeClient()
    text, _ = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert len(client.posts) == 1
    assert client.posts[0]["json"]["entity_id"] == "light.wohnzimmer_lese"


# ---------------------------------------------------------------------------
# Precedence stage 4 — no room anywhere → clarification, no execution
# ---------------------------------------------------------------------------
def test_no_room_asks_back(house, stub_lookup):
    stub_lookup({"licht": _light_on()})
    d = run(decide_path("Licht einschalten", client=None, source="webapp_cc"))
    assert d.path == "HA_FAST"
    assert d.area_targets[0].mode == "ask"

    client = FakeClient()
    text, results = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert client.posts == []
    assert results == []
    assert "welchem Raum" in text
    assert "Licht" in text


# ---------------------------------------------------------------------------
# Room known, no entity of the domain → LLM fallback
# ---------------------------------------------------------------------------
def test_room_without_matching_domain_falls_back_to_llm(house, stub_lookup):
    stub_lookup({"rolladen": IntentMatch(
        matched=True, certainty=0.9, entity_id="cover.buero",
        domain="cover", service="cover.close_cover", parameters={})})
    # Küche has no cover entity
    d = run(decide_path("Rolladen schließen", client=None, source="esphome:Küche"))
    assert d.path == "LLM_ONLY"


# ---------------------------------------------------------------------------
# Case-insensitive room match
# ---------------------------------------------------------------------------
def test_room_match_case_insensitive(house, stub_lookup):
    stub_lookup({"licht": _light_on()})
    d = run(decide_path("licht im büro einschalten", client=None, source=None))
    at = d.area_targets[0]
    assert at.mode == "area"
    assert at.area == "Büro"


# ---------------------------------------------------------------------------
# Partial failure — one of two lights offline
# ---------------------------------------------------------------------------
def test_partial_failure_named_separately(house, stub_lookup):
    stub_lookup({"licht": _light_on()})
    d = run(decide_path("Licht einschalten", client=None, source="esphome:Büro"))
    client = FakeClient(fail={"light.buero_stehlampe"})
    text, results = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert "Licht im Büro eingeschaltet, außer Büro Stehlampe" in text
    assert sum(1 for r in results if r["success"]) == 1


# ---------------------------------------------------------------------------
# All offline — nothing succeeded
# ---------------------------------------------------------------------------
def test_all_offline(house, stub_lookup):
    stub_lookup({"licht": _light_on()})
    d = run(decide_path("Licht einschalten", client=None, source="esphome:Büro"))
    client = FakeClient(fail={"light.buero_decke", "light.buero_stehlampe"})
    text, results = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert "nichts hat geklappt" in text
    assert all(not r["success"] for r in results)


# ---------------------------------------------------------------------------
# Value-bearing area command — same value to all
# ---------------------------------------------------------------------------
def test_value_applied_to_all_area_entities(house, stub_lookup):
    stub_lookup({"licht": IntentMatch(
        matched=True, certainty=0.9, entity_id="light.kueche_1", domain="light",
        service="light.turn_on", parameters={"brightness_pct": 50})})
    d = run(decide_path("Licht auf 30 Prozent dimmen", client=None,
                        source="esphome:Büro"))
    client = FakeClient()
    text, _ = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert all(p["json"]["brightness_pct"] == 30 for p in client.posts)
    assert len(client.posts) == 2
    assert "30 Prozent" in text


# ---------------------------------------------------------------------------
# Multi-command — each part gets its own area context
# ---------------------------------------------------------------------------
def test_multi_command_independent_area_context(house, stub_lookup):
    stub_lookup({
        "rolladen": IntentMatch(matched=True, certainty=0.9, entity_id="cover.buero",
                                domain="cover", service="cover.close_cover", parameters={}),
        "licht": _light_on(),
    })
    d = run(decide_path("Rolladen schließen und Licht ausschalten", client=None,
                        source="esphome:Büro"))
    assert d.path == "HA_FAST"
    assert d.area_targets[0].entity_ids == ["cover.buero"]
    assert set(d.area_targets[1].entity_ids) == {"light.buero_decke", "light.buero_stehlampe"}


# ---------------------------------------------------------------------------
# Multi-command — area part + shopping-list part
# ---------------------------------------------------------------------------
def test_area_plus_shopping(house, stub_lookup, monkeypatch):
    stub_lookup({"licht": _light_on()})

    class _P(FakePool):
        async def fetchrow(self, *a, **kw):
            return {"entity_id": "todo.einkaufsliste"}

    import app.memory as memory
    p = _P(HOUSE)
    monkeypatch.setattr(memory, "pool", lambda: p)

    d = run(decide_path("Licht einschalten und Butter auf die Einkaufsliste",
                        client=None, source="esphome:Büro"))
    assert d.path == "HA_FAST"
    assert d.shopping_items[-1] == "Butter"
    client = FakeClient()
    text, results = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert "Licht im Büro eingeschaltet" in text
    assert "Butter" in text


# ---------------------------------------------------------------------------
# Unknown room name in text, no device room → ask
# ---------------------------------------------------------------------------
def test_typo_room_name_falls_through_to_ask(house, stub_lookup):
    stub_lookup({"licht": _light_on()})
    d = run(decide_path("Licht im Bürro einschalten", client=None, source=None))
    assert d.area_targets[0].mode == "ask"


# ---------------------------------------------------------------------------
# BUG-1 (fixed) — area + temperature is range-checked per room entity, not
# against the arbitrary Weaviate match; its slug never leaks into the reply.
# ---------------------------------------------------------------------------
def test_area_temperature_uses_per_entity_bounds(house, stub_lookup):
    stub_lookup({"heizung": IntentMatch(
        matched=True, certainty=0.9, entity_id="climate.weaviate_match",
        domain="climate", service="climate.set_temperature",
        parameters={"temperature": 20})})
    d = run(decide_path("Heizung auf 27 Grad stellen", client=None,
                        source="esphome:Büro"))
    # Weaviate match would cap at 30; the real Büro entity supports up to 35.
    client = FakeClient(states={
        "climate.weaviate_match": {"min_temp": 5, "max_temp": 30},
        "climate.buero_ht": {"min_temp": 5, "max_temp": 35},
    })
    text, results = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert client.posts[0]["json"] == {"entity_id": "climate.buero_ht", "temperature": 27}
    assert text == "Heizung im Büro auf 27 Grad gestellt."
    assert "weaviate" not in text.lower()


def test_area_temperature_out_of_range_per_entity(house, stub_lookup):
    stub_lookup({"heizung": IntentMatch(
        matched=True, certainty=0.9, entity_id="climate.weaviate_match",
        domain="climate", service="climate.set_temperature",
        parameters={"temperature": 20})})
    d = run(decide_path("Heizung auf 45 Grad stellen", client=None,
                        source="esphome:Büro"))
    client = FakeClient(states={"climate.buero_ht": {"min_temp": 5, "max_temp": 30}})
    text, results = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert client.posts == []
    assert "Büro Heizung" in text and "5–30 Grad" in text


# ---------------------------------------------------------------------------
# BUG-2 (fixed) — out-of-range percent in area mode is rejected room-scoped,
# no HA call, no internal slug.
# ---------------------------------------------------------------------------
def test_area_percent_out_of_range_message_is_room_scoped(house, stub_lookup):
    stub_lookup({"licht": IntentMatch(
        matched=True, certainty=0.9, entity_id="light.weaviate_match",
        domain="light", service="light.turn_on",
        parameters={"brightness_pct": 50})})
    d = run(decide_path("Licht auf 150 Prozent dimmen", client=None,
                        source="esphome:Büro"))
    client = FakeClient()
    text, _ = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert client.posts == []
    assert "weaviate" not in text.lower()
    assert text == "Licht im Büro lässt sich nur zwischen 0 und 100 Prozent einstellen."


# ---------------------------------------------------------------------------
# BUG-3 (fixed) — domain noun + correct German preposition per room gender.
# ---------------------------------------------------------------------------
def test_area_message_grammar_feminine_room(house, stub_lookup):
    stub_lookup({"licht": _light_on()})
    d = run(decide_path("Licht einschalten", client=None, source="esphome:Küche"))
    client = FakeClient()
    text, _ = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert text == "Licht in der Küche eingeschaltet."


def test_area_message_grammar_masculine_room(house, stub_lookup):
    stub_lookup({"rolladen": IntentMatch(
        matched=True, certainty=0.9, entity_id="cover.x", domain="cover",
        service="cover.close_cover", parameters={})})
    d = run(decide_path("Rolladen schließen", client=None, source="esphome:Büro"))
    client = FakeClient()
    text, _ = run(execute_ha_intents(
        d.intents, client, parts=d.parts, shopping_items=d.shopping_items,
        area_targets=d.area_targets))
    assert text == "Rolladen im Büro geschlossen."
