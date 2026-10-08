"""PROJ-106 — templated replies for lists results (incl. combined day query)."""
from datetime import datetime

from app import lists_replies as lr
from app.calendar_replies import LOCAL_TZ

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=LOCAL_TZ)      # Thursday
SHOP = {"name": "Einkaufsliste", "shared": True, "shopping": True}
MINE = {"name": "Meine Aufgaben", "shared": False, "shopping": False}


def c(result, lang="de", channel="chat"):
    return lr.compose(result, lang, channel, now=NOW)


def test_added_shopping_enumerates():
    r = {"status": "added", "list": SHOP, "items": [{"title": "Milch"}, {"title": "Butter"}, {"title": "Eier"}],
         "reopened": []}
    assert c(r) == "Ich habe Milch, Butter und Eier auf die Einkaufsliste gesetzt."
    assert c(r, "en") == "I added Milch, Butter and Eier to the shopping list."


def test_added_task_with_due_time_deadline_priority():
    r = {"status": "added", "list": MINE, "reopened": [],
         "items": [{"title": "Reifen wechseln", "due": {"date": "2026-10-09", "time": "14:00"}}]}
    assert c(r) == "Ich habe „Reifen wechseln“ auf die Liste „Meine Aufgaben“ gesetzt, fällig morgen um 14:00 Uhr."
    assert c(r, channel="voice").endswith("fällig morgen um 14 Uhr.")
    r = {"status": "added", "list": MINE, "reopened": [],
         "items": [{"title": "Steuererklärung", "deadline": {"date": "2027-07-31"}, "priority": "high"}]}
    assert c(r) == ("Ich habe „Steuererklärung“ auf die Liste „Meine Aufgaben“ gesetzt, "
                    "Frist bis Samstag, 31. Juli, wichtig.")


def test_added_reopened_and_list_created():
    r = {"status": "added", "list": SHOP, "items": [], "reopened": [{"title": "Butter"}]}
    assert c(r) == "Butter stand schon abgehakt drauf, ich habe es wieder geöffnet."
    r = {"status": "added", "list": {"name": "Werkstatt", "shared": False, "shopping": False},
         "list_created": True, "items": [{"title": "Dübel"}], "reopened": []}
    assert c(r) == ("Ich habe die Liste „Werkstatt“ angelegt. "
                    "Ich habe „Dübel“ auf die Liste „Werkstatt“ gesetzt.")


def test_questions():
    assert c({"status": "unknown_list", "name": "Werkstatt"}) == \
        "Die Liste „Werkstatt“ gibt es nicht. Soll ich sie anlegen?"
    assert c({"status": "needs_list_scope", "name": "Baumarkt"}) == \
        "Meinst du deine private oder die gemeinsame Liste „Baumarkt“?"
    assert c({"status": "ambiguous_list", "options": ["Urlaub Italien", "Urlaub Spanien"]}) == \
        "Welche Liste meinst du: „Urlaub Italien“ oder „Urlaub Spanien“?"
    assert c({"status": "confirm_past", "field": "due", "item": {"title": "Alt", "due": {"date": "2026-10-06"}}}) \
        == "Das Datum (am Dienstag, 6. Oktober) liegt in der Vergangenheit. Soll ich „Alt“ trotzdem so eintragen?"
    q = c({"status": "confirm_order", "item": {"title": "X", "due": {"date": "2026-10-16"},
                                               "deadline": {"date": "2026-10-15"}}})
    assert q.startswith("Die Frist (am Donnerstag, 15. Oktober) liegt vor der Fälligkeit")
    assert c({"status": "confirm_duplicate", "titles": ["Bericht"], "list": MINE}) == \
        "„Bericht“ steht schon offen auf der Liste „Meine Aufgaben“. Soll ich es trotzdem noch einmal eintragen?"


def test_query_shopping_and_search_and_count():
    r = {"status": "ok", "mode": "items", "list": SHOP, "range": {"keyword": "all"}, "total": 2,
         "items": [{"title": "Milch"}, {"title": "Butter"}], "remaining": 0}
    assert c(r) == "Auf der Einkaufsliste stehen: Milch und Butter."
    r = {"status": "ok", "mode": "items", "list": SHOP, "range": {"keyword": "all"}, "total": 0, "items": [],
         "remaining": 0}
    assert c(r) == "Die Einkaufsliste ist leer."
    assert c({"status": "ok", "mode": "search", "list": SHOP, "search": "Butter", "found": True,
              "range": {}, "items": []}) == "Ja, „Butter“ steht auf der Einkaufsliste."
    assert c({"status": "ok", "mode": "search", "list": SHOP, "search": "Käse", "found": False,
              "range": {}, "items": []}) == "Nein, „Käse“ steht nicht auf der Einkaufsliste."
    assert c({"status": "ok", "mode": "count", "list": {"name": "Baumarkt", "shopping": False}, "total": 3,
              "range": {}, "items": []}) == "Auf der Liste „Baumarkt“ stehen 3 offene Einträge."


def test_query_overdue_due_deadlines_and_empty():
    r = {"status": "ok", "mode": "items", "range": {"keyword": "overdue"}, "total": 1, "remaining": 0,
         "items": [{"title": "Reifen wechseln", "due": {"date": "2026-10-07"}, "overdue": True}]}
    assert c(r) == "Überfällig: „Reifen wechseln“ (überfällig, fällig gestern)."
    assert c({**r, "items": [], "total": 0}) == "Es ist nichts überfällig."
    r = {"status": "ok", "mode": "items", "range": {"keyword": "this_week"}, "only_deadlines": True,
         "total": 1, "remaining": 0, "items": [{"title": "Bericht", "deadline": {"date": "2026-10-10"}}]}
    assert c(r) == "Fristen diese Woche: „Bericht“ (Frist bis übermorgen)."
    assert c({**r, "items": [], "total": 0}) == "Diese Woche hast du keine Fristen."
    r = {"status": "ok", "mode": "items", "range": {"keyword": "today"}, "total": 0, "items": [], "remaining": 0}
    assert c(r) == "Heute steht nichts an."


def test_query_voice_max_five_plus_rest_no_markdown():
    items = [{"title": f"E{i}"} for i in range(5)]
    r = {"status": "ok", "mode": "items", "list": SHOP, "range": {"keyword": "all"}, "total": 8,
         "items": items, "remaining": 3}
    text = c(r, channel="voice")
    assert text == "Auf der Einkaufsliste stehen: E0, E1, E2, E3 und E4 und 3 weitere."
    assert "\n" not in text and "-" not in text


def test_query_chat_bullets_and_truncation():
    items = [{"title": f"Aufgabe {i}", "list": "Arbeit"} for i in range(5)]
    r = {"status": "ok", "mode": "items", "range": {"keyword": "all"}, "total": 60, "items": items,
         "remaining": 55, "truncated": True}
    text = c(r)
    assert text.startswith("Deine offenen Einträge:\n- „Aufgabe 0“ (auf Arbeit)")
    assert "(Liste gekürzt)" in text


def test_done_query():
    r = {"status": "ok", "mode": "done", "range": {"keyword": "this_week"}, "total": 1, "remaining": 0,
         "items": [{"title": "Reifen wechseln", "done_at": "2026-10-07"}]}
    assert c(r) == "Diese Woche erledigt: „Reifen wechseln“."
    r = {"status": "ok", "mode": "done", "list": SHOP, "range": {"keyword": "all"}, "total": 0, "items": []}
    assert c(r) == "Von der Einkaufsliste wurde in den letzten 30 Tagen nichts abgehakt."


def test_complete_reopen_with_already_and_not_found():
    r = {"status": "completed", "items": [{"title": "Reifen wechseln"}], "already": [], "not_found": []}
    assert c(r) == "Ich habe „Reifen wechseln“ abgehakt."
    r = {"status": "completed", "items": [], "already": ["Reifen wechseln"], "not_found": ["Fenster putzen"]}
    assert c(r) == "„Reifen wechseln“ war schon erledigt. „Fenster putzen“ habe ich nicht gefunden."
    assert c({"status": "reopened", "items": [{"title": "Reifen wechseln"}], "already": [], "not_found": []}) \
        == "Ich habe „Reifen wechseln“ wieder geöffnet."


def test_remove_shopping_and_delete_flow():
    r = {"status": "removed", "items": [{"title": "Butter", "list": "Einkaufsliste"}, {"title": "Eier"}],
         "not_found": []}
    assert c(r) == "Ich habe Butter und Eier entfernt."
    q = {"status": "confirm_delete", "ticket": "T", "item": {"title": "Reifen wechseln"}, "list": MINE,
         "removed": [], "not_found": [], "deferred": []}
    assert c(q) == "Soll ich „Reifen wechseln“ von der Liste „Meine Aufgaben“ löschen?"
    assert c({"status": "deleted", "kind": "item", "item": {"title": "Reifen wechseln"}}) == \
        "Ich habe „Reifen wechseln“ gelöscht."
    assert c({"error": "not_confirmed"}) == "Okay, ich habe nichts gelöscht."


def test_list_management():
    assert c({"status": "confirm_delete_list", "list": {"name": "Urlaub", "shopping": False}, "count": 3}) == \
        "Soll ich die Liste „Urlaub“ mit 3 Einträgen löschen?"
    assert c({"status": "confirm_delete_list", "list": {"name": "Einkaufsliste", "shopping": True}, "count": 1}) \
        == "„Einkaufsliste“ ist die Einkaufsliste. Soll ich sie mit 1 Eintrag wirklich löschen?"
    assert c({"status": "list_created", "list": {"name": "Urlaub", "shared": True}}) == \
        "Ich habe die gemeinsame Liste „Urlaub“ angelegt."
    assert c({"status": "shopping_set", "list": {"name": "Lidl"}, "previous": "Einkaufsliste"}) == \
        "„Lidl“ ist jetzt die Einkaufsliste statt „Einkaufsliste“."
    assert c({"status": "default_set", "list": {"name": "Arbeit"}}) == "„Arbeit“ ist jetzt deine Standardliste."
    assert c({"status": "list_renamed", "old": "Arbeit", "list": {"name": "Büro"}}) == \
        "Ich habe die Liste „Arbeit“ in „Büro“ umbenannt."
    ov = c({"status": "lists", "lists": [
        {"name": "Meine Aufgaben", "default": True, "open": 2},
        {"name": "Einkaufsliste", "shared": True, "shopping": True, "open": 3}]})
    assert ov == "Deine Listen: Meine Aufgaben (Standard, 2 offen) und Einkaufsliste (Einkaufsliste, 3 offen)."


def test_errors():
    assert c({"error": "unknown_speaker"}).startswith("Ich weiß nicht, wer spricht")
    assert c({"error": "forbidden_child_remove"}) == "Von der Einkaufsliste entfernen darfst du nicht – abhaken geht aber."
    assert c({"error": "no_shopping_list"}).endswith("das kann ein Admin erledigen.")
    assert c({"error": "invalid_input"}) is None
    assert c({"error": "ticket_same_turn"}) is None
    assert c({"error": "something_new"}).startswith("Da ist etwas schiefgegangen")


def test_terminal():
    assert lr.is_terminal({"status": "added"})
    assert lr.is_terminal({"error": "forbidden"})
    assert not lr.is_terminal({"status": "confirm_delete"})
    assert not lr.is_terminal({"error": "invalid_input"})


# ---------------------------------------------------------------------------
# Combined day query
# ---------------------------------------------------------------------------
EVENT = {"title": "Zahnarzt", "date": "2026-10-09", "all_day": False, "start_time": "10:00"}
RANGE = {"from": "2026-10-09", "to": "2026-10-09", "next_only": False}


def _agenda(cal, lists):
    return {"status": "agenda", "calendar": cal, "lists": lists}


def test_agenda_events_then_items():
    r = _agenda({"status": "ok", "range": RANGE, "events": [EVENT], "total": 1},
                {"status": "ok", "range": {"keyword": "tomorrow"}, "total": 1,
                 "items": [{"title": "Reifen wechseln", "due": {"date": "2026-10-09", "time": "14:00"}}]})
    assert c(r) == ("Morgen hast du 1 Termin: um 10:00 Uhr Zahnarzt. "
                    "Fällig: „Reifen wechseln“ (fällig morgen um 14:00 Uhr).")


def test_agenda_voice_total_five_plus_rest():
    events = [dict(EVENT, title=f"T{i}") for i in range(4)]
    items = [{"title": f"A{i}"} for i in range(3)]
    r = _agenda({"status": "ok", "range": RANGE, "events": events, "total": 4},
                {"status": "ok", "range": {"keyword": "tomorrow"}, "total": 3, "items": items})
    text = c(r, channel="voice")
    assert "T3" in text and "A0" in text and "A1" not in text and text.endswith("Und 2 weitere.")


def test_agenda_nothing_and_calendar_missing():
    r = _agenda({"status": "ok", "range": RANGE, "events": [], "total": 0},
                {"status": "ok", "range": {"keyword": "tomorrow"}, "total": 0, "items": []})
    assert c(r) == "Morgen steht nichts an."
    # no calendar permission / connection → items only, silently
    r = _agenda({"error": "no_active_calendar"},
                {"status": "ok", "range": {"keyword": "tomorrow"}, "total": 1, "items": [{"title": "A"}]})
    assert c(r) == "Morgen fällig: „A“."
    # calendar not reachable → items plus a hint
    r = _agenda({"error": "calendar_unavailable"},
                {"status": "ok", "range": {"keyword": "tomorrow"}, "total": 1, "items": [{"title": "A"}]})
    assert c(r).endswith("Der Kalender war nicht erreichbar.")
    r = _agenda(None, {"status": "ok", "range": {"keyword": "today"}, "total": 0, "items": []})
    assert c(r) == "Heute steht nichts an."


def test_agenda_lists_forbidden_or_unknown_speaker():
    r = _agenda({"status": "ok", "range": RANGE, "events": [EVENT], "total": 1}, {"error": "forbidden"})
    assert c(r) == "Morgen hast du 1 Termin: um 10:00 Uhr Zahnarzt."
    r = _agenda(None, {"error": "unknown_speaker"})
    assert c(r).startswith("Ich weiß nicht, wer spricht")


def test_agenda_hint_when_lists_unavailable():
    """QA BUG-4: a missing entries part is mentioned."""
    r = _agenda({"status": "ok", "range": RANGE, "events": [EVENT], "total": 1}, {"error": "lists_unavailable"})
    assert c(r) == "Morgen hast du 1 Termin: um 10:00 Uhr Zahnarzt. Die Aufgaben waren nicht abrufbar."


def test_reserved_name_error():
    assert c({"error": "reserved_name"}).startswith("Dieser Name ist der Einkaufsliste vorbehalten")
