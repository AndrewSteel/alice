"""PROJ-83 — decide_path() routing for shopping-list and value commands."""
import asyncio

import pytest

import app.ha_path as ha_path
from app.ha_path import IntentMatch, decide_path, split_message


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


# ---------------------------------------------------------------------------
# PROJ-85 live-usage follow-up — split_message must not tear a transcribed
# clock time or decimal duration apart on '.'/',' between digits.
# ---------------------------------------------------------------------------
class TestSplitMessageDigitPunctuation:
    def test_clock_time_with_period_stays_one_part(self):
        # a plausible Whisper transcription of "18 Uhr 30"
        assert split_message("Setze einen Timer auf 18.30 Uhr") == [
            "Setze einen Timer auf 18.30 Uhr"
        ]

    def test_clock_time_with_comma_stays_one_part(self):
        assert split_message("Setze einen Timer auf 18,30 Uhr") == [
            "Setze einen Timer auf 18,30 Uhr"
        ]

    def test_decimal_duration_stays_one_part(self):
        assert split_message("Setze einen Timer auf 2,5 Minuten") == [
            "Setze einen Timer auf 2,5 Minuten"
        ]

    def test_sentence_ending_period_still_splits(self):
        assert split_message("Setze einen Timer auf 10 Minuten. Wie spät ist es") == [
            "Setze einen Timer auf 10 Minuten",
            "Wie spät ist es",
        ]

    def test_comma_separated_multi_command_still_splits(self):
        parts = split_message(
            "Timer auf 10 Minuten, und einen auf 20 Minuten"
        )
        assert parts == ["Timer auf 10 Minuten", "einen auf 20 Minuten"]


def test_clock_time_with_period_transcription_routes_as_clock(stub_lookup):
    # End-to-end: a Whisper transcription rendering "18 Uhr 30" as "18.30
    # Uhr" must still reach the timer handler as ONE unsplit part naming a
    # clock time, not be torn into "...auf 18" (mis-parsed as 18 minutes)
    # and a stray "30 uhr" fragment.
    stub_lookup({"timer": _match(domain="timer", service="timer.set",
                                 intent_template="timer:set")})
    d = run(decide_path("Setze einen Timer auf 18.30 Uhr", client=None))
    assert d.path == "HA_FAST"
    assert d.parts == ["Setze einen Timer auf 18.30 Uhr"]
    assert d.timer_actions == ["set"]
