"""PROJ-83 — decide_path() routing for shopping-list and value commands."""
import asyncio

import pytest

import app.ha_path as ha_path
from app.ha_path import IntentMatch, decide_path


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def stub_lookup(monkeypatch):
    """Route lookup_intent by a {substring: IntentMatch} table."""
    def _install(table, default=None):
        async def fake_lookup(part, client):
            for key, val in table.items():
                if key in part.lower():
                    return val
            return default or IntentMatch(matched=False, certainty=0.0)
        monkeypatch.setattr(ha_path, "lookup_intent", fake_lookup)
    return _install


def _match(**kw):
    return IntentMatch(matched=True, certainty=0.9, **kw)


def test_shopping_list_routes_ha_fast(stub_lookup):
    stub_lookup({})  # nothing matches in Weaviate
    d = run(decide_path("Milch zur Einkaufsliste hinzufügen", client=None))
    assert d.path == "HA_FAST"
    assert d.shopping_items == ["Milch"]


def test_plain_free_text_still_llm_only(stub_lookup):
    stub_lookup({})
    d = run(decide_path("Wie wird das Wetter morgen", client=None))
    assert d.path == "LLM_ONLY"


def test_value_command_routes_ha_fast(stub_lookup):
    stub_lookup({"rolladen": _match(entity_id="cover.buro", domain="cover",
                                    service="cover.set_cover_position",
                                    parameters={"position": 50})})
    d = run(decide_path("Rolladen im Büro auf 37 Prozent stellen", client=None))
    assert d.path == "HA_FAST"
    assert d.shopping_items == [None]


def test_multi_command_value_plus_shopping(stub_lookup):
    stub_lookup({"licht": _match(entity_id="light.wohnzimmer", domain="light",
                                 service="light.turn_on",
                                 parameters={"brightness_pct": 50})})
    d = run(decide_path(
        "Licht im Wohnzimmer auf 30 Prozent und Butter auf die Einkaufsliste",
        client=None))
    assert d.path == "HA_FAST"
    assert d.shopping_items[-1] == "Butter"
    assert d.shopping_items[0] is None


# ---------------------------------------------------------------------------
# PROJ-85 — timer intents route HA_FAST and are marked in timer_actions
# ---------------------------------------------------------------------------
def test_timer_set_routes_ha_fast(stub_lookup):
    stub_lookup({"timer": _match(domain="timer", service="timer.set",
                                 intent_template="timer:set")})
    d = run(decide_path("Setze einen Timer auf 20 Minuten", client=None))
    assert d.path == "HA_FAST"
    assert d.timer_actions == ["set"]
    # no area resolution attempted for a timer part
    assert d.area_targets == [None]


def test_two_timers_one_sentence(stub_lookup):
    stub_lookup({"timer": _match(domain="timer", service="timer.set",
                                 intent_template="timer:set")})
    d = run(decide_path("Setze einen Timer auf 10 und einen Timer auf 20 Minuten",
                        client=None))
    assert d.path == "HA_FAST"
    assert d.timer_actions == ["set", "set"]


def test_timer_plus_ha_command(stub_lookup):
    stub_lookup({
        "timer": _match(domain="timer", service="timer.delete",
                        intent_template="timer:delete"),
        "licht": _match(entity_id="light.wohnzimmer", domain="light",
                        service="light.turn_on", parameters={}),
    })
    d = run(decide_path("Lösche alle Timer und Licht im Wohnzimmer an", client=None))
    assert d.path == "HA_FAST"
    assert d.timer_actions[0] == "delete"
    assert d.timer_actions[1] is None
