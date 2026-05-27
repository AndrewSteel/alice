"""Tests for the sentence accumulator — token stream -> complete sentences."""
from app.sentence_accumulator import SentenceAccumulator


def test_no_terminator_buffers_until_flush():
    acc = SentenceAccumulator()
    assert acc.feed("Hallo ") == []
    assert acc.feed("Welt") == []
    assert acc.flush() == "Hallo Welt"


def test_period_completes_sentence():
    acc = SentenceAccumulator()
    out = acc.feed("Das ist ein Satz.")
    assert out == ["Das ist ein Satz."]
    assert acc.flush() is None


def test_terminators_question_exclamation_newline():
    acc = SentenceAccumulator()
    assert acc.feed("Wirklich? ") == ["Wirklich?"]
    assert acc.feed("Toll! ") == ["Toll!"]
    assert acc.feed("Zeile\n") == ["Zeile"]


def test_multiple_sentences_in_one_token():
    acc = SentenceAccumulator()
    # All three end with a terminator -> all three are complete sentences.
    out = acc.feed("Erster Satz. Zweiter Satz! Dritter?")
    assert out == ["Erster Satz.", "Zweiter Satz!", "Dritter?"]
    assert acc.flush() is None


def test_trailing_partial_after_complete_sentences():
    acc = SentenceAccumulator()
    out = acc.feed("Fertig. Noch nicht")
    assert out == ["Fertig."]
    assert acc.flush() == "Noch nicht"


def test_sentence_split_across_tokens():
    acc = SentenceAccumulator()
    assert acc.feed("Ein ") == []
    assert acc.feed("langer ") == []
    assert acc.feed("Satz.") == ["Ein langer Satz."]


def test_empty_token_is_noop():
    acc = SentenceAccumulator()
    assert acc.feed("") == []
    assert acc.flush() is None


def test_flush_clears_buffer():
    acc = SentenceAccumulator()
    acc.feed("Rest ohne Punkt")
    assert acc.flush() == "Rest ohne Punkt"
    assert acc.flush() is None
