"""German check of title and summary (AK-22–24, EC-12)."""
from app.language import not_german, suspicious

T = 0.15


def test_english_summary_is_suspicious():
    assert not_german("This is an invoice from the electricity provider for the month of October.", T)


def test_german_with_english_terms_is_not():  # AK-24
    assert not not_german("Rechnung für Cloud Storage und Premium Support Services der Firma Example "
                          "für den Monat Oktober, bezahlt per Credit Card.", T)


def test_names_and_numbers_are_not():  # AK-24, EC-12
    assert not not_german("Amazon Web Services 2026", T)
    assert not not_german("", T)
    assert not suspicious("Vodafone GmbH 4711", "Kurz.", T)


def test_german_text():
    assert not not_german("Die Stadtwerke rechnen den Stromverbrauch für Oktober ab. Der Betrag wird am "
                          "Monatsende eingezogen.", T)
