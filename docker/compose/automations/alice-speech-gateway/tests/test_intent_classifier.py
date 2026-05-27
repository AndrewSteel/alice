"""Tests for the barge-in intent classifier (stage 3, rule-based)."""
from app.barge_in import IntentClassifier

PHRASES = [
    "stop",
    "stopp",
    "halt",
    "warte mal",
    "moment",
    "ich habe eine frage",
    "da widerspreche ich",
]


def test_exact_interrupt_phrase_matches():
    clf = IntentClassifier(PHRASES)
    assert clf.is_interrupt("Stop")
    assert clf.is_interrupt("stopp")
    assert clf.is_interrupt("Moment")


def test_multi_word_phrase_matches():
    clf = IntentClassifier(PHRASES)
    assert clf.is_interrupt("Ja warte mal kurz")
    assert clf.is_interrupt("Ich habe eine Frage dazu")


def test_case_insensitive():
    clf = IntentClassifier(PHRASES)
    assert clf.is_interrupt("HALT BITTE")


def test_whole_word_only_no_substring_false_positive():
    clf = IntentClassifier(PHRASES)
    # "haltestelle" must NOT match "halt", "stoppen" must NOT match "stopp" —
    # word-boundary matching prevents these false positives.
    assert not clf.is_interrupt("Die Bushaltestelle ist dort")
    assert not clf.is_interrupt("stoppen")


def test_background_noise_no_interrupt():
    clf = IntentClassifier(PHRASES)
    # TV / radio transcript with no interrupt phrase -> discarded.
    assert not clf.is_interrupt("und jetzt zum Wetter in der Region")
    assert not clf.is_interrupt("das war ein schoenes Tor von der Mannschaft")


def test_empty_transcript_no_interrupt():
    clf = IntentClassifier(PHRASES)
    assert not clf.is_interrupt("")
    assert not clf.is_interrupt("   ")
