"""PROJ-87: templated calendar replies (live finding: verbose, duplicate LLM output)."""
from datetime import datetime

import pytest

from app import calendar_replies as cr

NOW = datetime(2026, 10, 5, 20, 0, tzinfo=cr.LOCAL_TZ)   # Monday
EV = {"title": "Test", "date": "2026-10-06", "weekday": "Tuesday", "all_day": False,
      "start_time": "10:00", "end_time": "11:00", "calendar": "Privatkalender"}


def c(result, lang="de", channel="voice"):
    return cr.compose(result, lang, channel, NOW)


def test_live_scenario_delete_question_is_one_short_sentence():
    text = c({"status": "confirm_delete", "ticket": "T", "scope": "single", "event": EV})
    assert text == "Soll ich „Test“ morgen um 10 Uhr löschen?"
    assert "Serie" not in text


def test_live_scenario_deleted_is_short():
    assert c({"status": "deleted", "scope": "single", "event": EV}) == "Ich habe den Termin „Test“ gelöscht."


def test_series_wording_only_when_series():
    assert "ganze Serie" in c({"status": "confirm_delete", "scope": "series", "event": EV})
    assert c({"status": "needs_scope", "event": {**EV, "recurring": True}}).endswith(
        "Nur diesen Termin oder die ganze Serie?")


def test_created_names_calendar_and_time():
    assert c({"status": "created", "event": EV}) == \
        "Ich habe „Test“ morgen um 10 Uhr in den Kalender „Privatkalender“ eingetragen."
    assert c({"status": "created", "event": {**EV, "start_time": "09:20"}}, channel="chat") == \
        "Ich habe „Test“ morgen um 9:20 Uhr in den Kalender „Privatkalender“ eingetragen."


def test_voice_time_is_spoken():
    assert "um 9 Uhr 20" in c({"status": "created", "event": {**EV, "start_time": "09:20"}})


def test_list_voice_single_sentence_with_remaining():
    r = {"status": "ok", "range": {"from": "2026-10-06", "to": "2026-10-06", "next_only": False},
         "events": [{**EV, "title": "Fußpflege", "start_time": "09:20"}, EV], "total": 7, "remaining": 5}
    assert c(r) == "Morgen hast du 7 Termine: um 9 Uhr 20 Fußpflege und um 10 Uhr Test und 5 weitere."


def test_list_empty_and_next():
    assert c({"status": "ok", "range": {"from": "2026-10-05", "to": "2026-10-05"}, "events": [],
              "total": 0}) == "Heute hast du keine Termine."
    assert c({"status": "ok", "range": {"from": "2026-10-05", "to": "2027-10-05", "next_only": True},
              "events": [EV], "total": 1}) == "Dein nächster Termin: „Test“ morgen um 10 Uhr."


def test_list_chat_uses_lines_for_many_events():
    evs = [{**EV, "title": f"T{i}", "date": "2026-10-1" + str(i)} for i in range(2, 7)]
    r = {"status": "ok", "range": {"from": "2026-10-12", "to": "2026-10-18"}, "events": evs, "total": 5}
    text = c(r, channel="chat")
    assert text.startswith("Vom 12. Oktober bis 18. Oktober hast du 5 Termine:")
    assert text.count("\n- ") == 5 and "(Privatkalender)" in text


def test_list_warns_about_failed_account():
    r = {"status": "ok", "range": {"from": "2026-10-05", "to": "2026-10-05"}, "events": [],
         "total": 0, "warnings": [{"account": "work@firma.de", "problem": "reauth_required"}]}
    assert "work@firma.de war nicht abrufbar" in c(r)


def test_ambiguous_voice_capped_to_three():
    cands = [{**EV, "title": f"Meeting {i}"} for i in range(5)]
    text = c({"status": "ambiguous", "candidates": cands})
    assert text.count("Meeting") == 3 and text.endswith("?") and " oder " in text


def test_multi_day_all_day():
    ev = {"title": "Urlaub", "date": "2026-10-12", "all_day": True, "end_date": "2026-10-16"}
    assert "von Montag, 12. Oktober bis Freitag, 16. Oktober" in c({"status": "created", "event": ev})


@pytest.mark.parametrize("err,needle", [
    ("reauth_required", "Einstellungen → Kalender"),
    ("calendar_unavailable", "nicht erreichbar"),
    ("unsupported_recurrence", "Google Kalender"),
    ("unknown_speaker", "nicht erkannt"),
    ("forbidden", "keinen Zugriff"),
    ("event_changed", "nicht gelöscht"),
    ("ticket_expired", "nichts gelöscht"),
    ("something_new", "nicht erreichbar"),   # unknown error → safe generic text, never success
])
def test_errors(err, needle):
    assert needle in c({"error": err, "message": "x"})


@pytest.mark.parametrize("err", ["invalid_input", "await_user_answer", "ticket_same_turn"])
def test_llm_handles_correctable_errors(err):
    assert c({"error": err, "message": "x"}) is None


def test_english():
    assert c({"status": "confirm_delete", "scope": "single", "event": EV}, lang="en") == \
        "Shall I delete “Test” tomorrow at 10:00?"
    assert c({"status": "deleted", "scope": "single", "event": EV}, lang="englisch") == "I deleted “Test”."


def test_unknown_language_falls_back_to_german():
    assert c({"status": "deleted", "event": EV}, lang="fr").startswith("Ich habe")


def test_terminal_detection():
    assert cr.is_terminal({"status": "deleted"}) and cr.is_terminal({"error": "x"})
    assert not cr.is_terminal({"status": "confirm_delete"})
