"""PROJ-83 — unit tests for value re-extraction, classification and
shopping-list detection in ha_path.py.

Only the pure (non-async, no-httpx) helpers are exercised here; conftest.py
stubs httpx, so the HTTP-touching paths are covered by /qa integration.
"""
from app.ha_path import (  # noqa: E402
    classify_value_type,
    detect_shopping_list_item,
    extract_numeric_value,
)


# ---------------------------------------------------------------------------
# extract_numeric_value
# ---------------------------------------------------------------------------
class TestExtractNumericValue:
    def test_plain_digits(self):
        assert extract_numeric_value("auf 50 Prozent stellen") == 50

    def test_temperature_digits(self):
        assert extract_numeric_value("Heizung auf 21 Grad") == 21

    def test_decimal_comma_rounds_up(self):
        assert extract_numeric_value("21,5 Grad") == 22

    def test_decimal_comma_rounds_down(self):
        assert extract_numeric_value("21,4 Grad") == 21

    def test_decimal_dot(self):
        assert extract_numeric_value("auf 74.6 Prozent") == 75

    def test_leading_zeros(self):
        assert extract_numeric_value("auf 050 Prozent") == 50

    def test_zero(self):
        assert extract_numeric_value("Rolladen auf 0 Prozent") == 0

    def test_hundred(self):
        assert extract_numeric_value("Licht auf 100 Prozent") == 100

    def test_out_of_range_value_still_extracted(self):
        # Range check happens later; extraction just returns the number.
        assert extract_numeric_value("Heizung auf 45 Grad") == 45

    def test_no_number(self):
        assert extract_numeric_value("Rolladen auf stellen") is None

    def test_first_number_wins(self):
        assert extract_numeric_value("Rolladen 2 im Büro auf 30 Prozent") == 2

    def test_half_rounds_up_commercial(self):
        # Python's round(0.5) == 0 (banker's); we want 1.
        assert extract_numeric_value("0,5 Grad") == 1
        assert extract_numeric_value("2,5 Grad") == 3


# ---------------------------------------------------------------------------
# classify_value_type
# ---------------------------------------------------------------------------
class TestClassifyValueType:
    def test_light_brightness(self):
        assert classify_value_type("light.turn_on", {"brightness_pct": 50}) == ("percent", "brightness_pct")

    def test_cover_position_param(self):
        assert classify_value_type("cover.set_cover_position", {"position": 25}) == ("percent", "position")

    def test_cover_position_empty_params(self):
        assert classify_value_type("cover.set_cover_position", {}) == ("percent", "position")

    def test_climate_temperature(self):
        assert classify_value_type("climate.set_temperature", {"temperature": 20}) == ("temperature", "temperature")

    def test_generic_value_key(self):
        assert classify_value_type("cover.set_cover_position", {"value": 40}) == ("percent", "value")

    def test_non_value_intent(self):
        assert classify_value_type("light.turn_on", {}) is None
        assert classify_value_type("cover.open_cover", {}) is None
        assert classify_value_type("light.turn_off", None) is None

    def test_temperature_wins_over_percent(self):
        assert classify_value_type("x.y", {"temperature": 5, "brightness_pct": 5}) == ("temperature", "temperature")


# ---------------------------------------------------------------------------
# detect_shopping_list_item
# ---------------------------------------------------------------------------
class TestDetectShoppingListItem:
    def test_zur_einkaufsliste_hinzufuegen(self):
        assert detect_shopping_list_item("Milch zur Einkaufsliste hinzufügen") == "Milch"

    def test_auf_die_einkaufsliste(self):
        assert detect_shopping_list_item("Butter auf die Einkaufsliste") == "Butter"

    def test_schreib_prefix(self):
        assert detect_shopping_list_item("schreib Käse auf die Einkaufsliste") == "Käse"

    def test_quantity_in_item(self):
        assert detect_shopping_list_item("2 Packungen Milch zur Einkaufsliste hinzufügen") == "2 Packungen Milch"

    def test_long_free_text_item(self):
        txt = "einen großen Sack Kartoffeln für das Wochenende zur Einkaufsliste hinzufügen"
        assert detect_shopping_list_item(txt) == "einen großen Sack Kartoffeln für das Wochenende"

    def test_einkaufszettel_synonym(self):
        assert detect_shopping_list_item("Eier auf den Einkaufszettel") == "Eier"

    def test_not_a_shopping_command(self):
        assert detect_shopping_list_item("Licht im Wohnzimmer einschalten") is None
        assert detect_shopping_list_item("Rolladen im Büro auf 50 Prozent stellen") is None

    def test_setze_auf_die_liste(self):
        assert detect_shopping_list_item("setze Tomaten auf die Einkaufsliste") == "Tomaten"

    def test_meine_einkaufsliste(self):
        assert detect_shopping_list_item("Zwiebeln zu meiner Einkaufsliste hinzufügen") == "Zwiebeln"
