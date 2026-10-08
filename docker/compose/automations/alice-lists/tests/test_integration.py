"""
Agent behaviour against a real PostgreSQL (see conftest: LISTS_TEST_DSN),
organised along the PROJ-106 acceptance criteria.
"""
import time
from datetime import datetime, timedelta

import pytest

from app import agent, db
from tests.conftest import ADMIN, CHILD, TZ, USER, USER2, make_ctx

pytestmark = pytest.mark.usefixtures("pool")


def _titles(result, key="items"):
    return [i["title"] for i in result[key]]


async def _add(user, items, **args):
    return await agent.add_items(make_ctx(user), {"items": items, **args})


def _iso(days=0):
    return (datetime.now(TZ).date() + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------
async def test_default_list_is_created_on_first_use():
    r = await _add(USER, "Reifen wechseln")
    assert r["status"] == "added" and r["list"]["name"] == "Meine Aufgaben" and not r["list"]["shared"]
    ov = await agent.manage_list(make_ctx(USER), {"action": "overview"})
    mine = [l for l in ov["lists"] if l["name"] == "Meine Aufgaben"]
    assert mine and mine[0]["default"] and mine[0]["open"] == 1
    assert any(l["shopping"] for l in ov["lists"])


async def test_private_lists_are_invisible_to_others_incl_admin():
    await agent.manage_list(make_ctx(USER), {"action": "create", "name": "Geheim"})
    await _add(USER, "Geschenk kaufen", list="Geheim")
    for other in (ADMIN, USER2):
        ov = await agent.manage_list(make_ctx(other), {"action": "overview"})
        assert "Geheim" not in [l["name"] for l in ov["lists"]]
        q = await agent.query_items(make_ctx(other), {"search": "Geschenk"})
        assert q["total"] == 0
        r = await _add(other, "x", list="Geheim")
        assert r["status"] == "unknown_list"


async def test_names_unique_case_insensitive_among_visible():
    assert (await agent.manage_list(make_ctx(USER), {"action": "create", "name": "Baumarkt"}))["status"] == "list_created"
    dup = await agent.manage_list(make_ctx(USER), {"action": "create", "name": "baumarkt"})
    assert dup["error"] == "duplicate_list_name"
    dup = await agent.manage_list(make_ctx(USER), {"action": "create", "name": "BAUMARKT", "shared": True})
    assert dup["error"] == "duplicate_list_name"
    # another user's invisible private list does not block a shared name
    ok = await agent.manage_list(make_ctx(USER2), {"action": "create", "name": "Baumarkt", "shared": True})
    assert ok["status"] == "list_created" and ok["list"]["shared"]
    # the owner of the private one now has to choose
    q = await _add(USER, "Dübel", list="Baumarkt")
    assert q["status"] == "needs_list_scope"
    r = await _add(USER, "Dübel", list="Baumarkt", list_scope="shared")
    assert r["status"] == "added" and r["list"]["shared"]


async def test_approximate_list_name_and_unknown_list_question():
    await agent.manage_list(make_ctx(USER), {"action": "create", "name": "Baumarkt"})
    r = await _add(USER, "Schrauben", list="Baumarktliste")
    assert r["status"] == "added" and r["list"]["name"] == "Baumarkt"
    q = await _add(USER, "Dübel", list="Werkstatt")
    assert q["status"] == "unknown_list" and q["name"] == "Werkstatt"
    # a model setting confirmed=true without a pending question is ignored
    # (main.py), here: the confirmed answer in the next turn creates it
    r = await agent.add_items(make_ctx(USER, turn=2, confirmed=True), {"items": "Dübel", "list": "Werkstatt"})
    assert r["status"] == "added" and r["list_created"] and r["list"]["name"] == "Werkstatt"


async def test_ambiguous_list_name():
    for n in ("Urlaub Italien", "Urlaub Spanien"):
        await agent.manage_list(make_ctx(USER), {"action": "create", "name": n})
    q = await _add(USER, "Sonnencreme", list="Urlaub")
    assert q["status"] == "ambiguous_list" and set(q["options"]) == {"Urlaub Italien", "Urlaub Spanien"}


async def test_rename_set_default_and_delete_with_count():
    await agent.manage_list(make_ctx(USER), {"action": "create", "name": "Arbeit"})
    r = await agent.manage_list(make_ctx(USER), {"action": "set_default", "name": "Arbeit"})
    assert r["status"] == "default_set"
    assert (await _add(USER, "Bericht schreiben, Mails"))["list"]["name"] == "Arbeit"
    r = await agent.manage_list(make_ctx(USER), {"action": "rename", "name": "Arbeit", "new_name": "Büro"})
    assert r["status"] == "list_renamed" and r["old"] == "Arbeit" and r["list"]["name"] == "Büro"
    q = await agent.manage_list(make_ctx(USER, turn=3), {"action": "delete", "name": "Büro"})
    assert q["status"] == "confirm_delete_list" and q["count"] == 2
    d = await agent.confirm_delete(make_ctx(USER, turn=4), {"ticket": q["ticket"]})
    assert d["status"] == "deleted" and d["kind"] == "list"
    # default falls back to "Meine Aufgaben"
    assert (await _add(USER, "Neu"))["list"]["name"] == "Meine Aufgaben"


async def test_deleted_my_tasks_is_recreated():
    await _add(USER, "a")
    q = await agent.manage_list(make_ctx(USER, turn=1), {"action": "delete", "name": "Meine Aufgaben"})
    await agent.confirm_delete(make_ctx(USER, turn=2), {"ticket": q["ticket"]})
    r = await _add(USER, "b")
    assert r["list"]["name"] == "Meine Aufgaben"
    q = await agent.query_items(make_ctx(USER), {"list": "Meine Aufgaben"})
    assert _titles(q) == ["b"]


async def test_shared_list_rename_delete_only_admin_or_creator():
    await agent.manage_list(make_ctx(USER), {"action": "create", "name": "Urlaub", "shared": True})
    r = await agent.manage_list(make_ctx(USER2), {"action": "rename", "name": "Urlaub", "new_name": "Ferien"})
    assert r["error"] == "not_list_owner"
    r = await agent.manage_list(make_ctx(CHILD), {"action": "delete", "name": "Urlaub"})
    assert "error" in r
    r = await agent.manage_list(make_ctx(ADMIN), {"action": "rename", "name": "Urlaub", "new_name": "Ferien"})
    assert r["status"] == "list_renamed"
    r = await agent.manage_list(make_ctx(USER, turn=5), {"action": "delete", "name": "Ferien"})
    assert r["status"] == "confirm_delete_list"


async def test_child_cannot_create_shared_list():
    r = await agent.manage_list(make_ctx(CHILD), {"action": "create", "name": "Spiele", "shared": True})
    assert r["error"] == "forbidden"
    r = await agent.manage_list(make_ctx(CHILD), {"action": "create", "name": "Spiele"})
    assert r["status"] == "list_created"


async def test_user_deletion_cascades_private_keeps_shared(pool):
    await agent.manage_list(make_ctx(USER2), {"action": "create", "name": "Privat2"})
    await agent.manage_list(make_ctx(USER2), {"action": "create", "name": "Garten", "shared": True})
    await pool.execute("DELETE FROM alice.users WHERE id = $1::uuid", USER2)
    names = {r["name"]: r["created_by"] for r in await pool.fetch("SELECT name, created_by FROM alice.lists")}
    assert "Privat2" not in names and names["Garten"] is None
    r = await agent.manage_list(make_ctx(USER), {"action": "rename", "name": "Garten", "new_name": "G"})
    assert r["error"] == "not_list_owner"


# ---------------------------------------------------------------------------
# Shopping list
# ---------------------------------------------------------------------------
async def test_shopping_add_split_and_quantities():
    r = await _add(USER, "Milch, Butter und Eier", list="Einkaufsliste")
    assert r["status"] == "added" and _titles(r) == ["Milch", "Butter", "Eier"] and r["list"]["shopping"]
    r = await _add(USER, "Salz und Pfeffer", list="Einkaufszettel")
    assert _titles(r) == ["Salz", "Pfeffer"]
    r = await _add(USER, "2 Packungen Milch und 6 Eier", list="Einkaufsliste")
    assert _titles(r) == ["2 Packungen Milch", "6 Eier"]


async def test_shopping_duplicates_and_reopen_done():
    await _add(USER, "Milch", list="Einkaufsliste")
    r = await _add(USER2, "Milch", list="Einkaufsliste")
    assert _titles(r) == ["Milch"]                      # open duplicate: added silently
    await agent.complete_items(make_ctx(USER), {"items": "Butter", "list": "Einkaufsliste"})
    await _add(USER, "Butter", list="Einkaufsliste")
    c = await agent.complete_items(make_ctx(USER), {"items": "Butter", "list": "Einkaufsliste"})
    assert _titles(c) == ["Butter"]
    r = await _add(USER, "Butter", list="Einkaufsliste")
    assert r["items"] == [] and _titles(r, "reopened") == ["Butter"]


async def test_set_shopping_only_admin_and_flag_moves():
    await agent.manage_list(make_ctx(USER), {"action": "create", "name": "Lidl", "shared": True})
    r = await agent.manage_list(make_ctx(USER), {"action": "set_shopping", "name": "Lidl"})
    assert r["error"] == "admin_only"
    r = await agent.manage_list(make_ctx(ADMIN), {"action": "set_shopping", "name": "Lidl"})
    assert r["status"] == "shopping_set" and r["previous"] == "Einkaufsliste"
    r = await _add(USER, "Brot", list="Einkaufsliste")
    assert r["list"]["name"] == "Lidl"
    await agent.manage_list(make_ctx(ADMIN), {"action": "create", "name": "Privat"})
    r = await agent.manage_list(make_ctx(ADMIN), {"action": "set_shopping", "name": "Privat"})
    assert r["error"] == "private_not_shopping"


async def test_shopping_list_delete_only_admin_then_none():
    r = await agent.manage_list(make_ctx(USER), {"action": "delete", "name": "Einkaufsliste"})
    assert r["error"] == "admin_only"
    q = await agent.manage_list(make_ctx(ADMIN, turn=1), {"action": "delete", "name": "Einkaufsliste"})
    assert q["status"] == "confirm_delete_list" and q["list"]["shopping"]
    await agent.confirm_delete(make_ctx(ADMIN, turn=2), {"ticket": q["ticket"]})
    r = await _add(USER, "Milch", list="Einkaufsliste")
    assert r["error"] == "no_shopping_list"
    r = await agent.add_items(make_ctx(None), {"items": "Milch", "list": "Einkaufsliste"})
    assert r["error"] == "no_shopping_list"


async def test_shopping_remove_without_question_child_refused():
    await _add(USER, "Milch, Butter und Eier", list="Einkaufsliste")
    r = await agent.remove_items(make_ctx(CHILD), {"items": "Butter", "list": "Einkaufsliste"})
    assert r["error"] == "forbidden_child_remove"
    r = await agent.remove_items(make_ctx(USER), {"items": "Butter und Eier und Käse", "list": "Einkaufsliste"})
    assert r["status"] == "removed" and _titles(r) == ["Butter", "Eier"] and r["not_found"] == ["Käse"]
    q = await agent.query_items(make_ctx(USER), {"list": "Einkaufsliste"})
    assert _titles(q) == ["Milch"]


async def test_child_can_read_add_complete_shared():
    await _add(CHILD, "Schokolade", list="Einkaufsliste")
    assert (await agent.complete_items(make_ctx(CHILD), {"items": "Schokolade"}))["status"] == "completed"
    q = await agent.query_items(make_ctx(CHILD), {"list": "Einkaufsliste", "done": True})
    assert _titles(q) == ["Schokolade"]


# ---------------------------------------------------------------------------
# Unknown speaker
# ---------------------------------------------------------------------------
async def test_unknown_speaker_may_only_add_to_shopping():
    unknown = make_ctx(None)
    r = await agent.add_items(unknown, {"items": "Milch", "list": "Einkaufsliste"})
    assert r["status"] == "added"
    for call in (agent.query_items(unknown, {"list": "Einkaufsliste"}),
                 agent.add_items(unknown, {"items": "Milch"}),
                 agent.complete_items(unknown, {"items": "Milch"}),
                 agent.remove_items(unknown, {"items": "Milch", "list": "Einkaufsliste"}),
                 agent.manage_list(unknown, {"action": "overview"}),
                 agent.query_items(unknown, {"range": "tomorrow"})):
        assert (await call)["error"] == "unknown_speaker"
    await agent.manage_list(make_ctx(USER), {"action": "create", "name": "Urlaub", "shared": True})
    r = await agent.add_items(unknown, {"items": "x", "list": "Urlaub"})
    assert r["status"] == "unknown_list"   # only the shopping list is visible to him


# ---------------------------------------------------------------------------
# Fields, dates, duplicates
# ---------------------------------------------------------------------------
async def test_due_with_time_deadline_priority():
    r = await _add(USER, "Reifen wechseln", due_date=_iso(1), due_time="14:00")
    assert r["items"][0]["due"] == {"date": _iso(1), "time": "14:00"}
    r = await _add(USER, "Steuererklärung", deadline_date=_iso(30), priority="high")
    item = r["items"][0]
    assert item["deadline"] == {"date": _iso(30)} and item["priority"] == "high" and "due" not in item


async def test_past_date_and_order_conflict_ask():
    q = await _add(USER, "Alt", due_date=_iso(-2))
    assert q["status"] == "confirm_past" and q["field"] == "due"
    q = await _add(USER, "Konflikt", due_date=_iso(5), deadline_date=_iso(4))
    assert q["status"] == "confirm_order"
    assert (await agent.query_items(make_ctx(USER), {}))["total"] == 0   # nothing stored
    r = await agent.add_items(make_ctx(USER, confirmed=True), {"items": "Alt", "due_date": _iso(-2)})
    assert r["status"] == "added"


async def test_duplicate_outside_shopping_asks():
    await _add(USER, "Bericht")
    q = await _add(USER, "bericht, Folien")
    assert q["status"] == "confirm_duplicate" and q["titles"] == ["bericht"]
    r = await agent.add_items(make_ctx(USER, confirmed=True), {"items": "bericht, Folien"})
    assert _titles(r) == ["bericht", "Folien"]


async def test_long_entry_kept():
    long = "Den Keller aufräumen und dabei alte Kartons zum Wertstoffhof bringen"
    r = await _add(USER, long.replace(" und ", " sowie "))
    assert r["items"][0]["title"] == long.replace(" und ", " sowie ")


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
async def test_sorting_overdue_date_priority_undated(pool):
    ctx = make_ctx(USER)
    await _add(USER, "ohne Datum")
    await _add(USER, "morgen normal", due_date=_iso(1))
    await _add(USER, "morgen wichtig", deadline_date=_iso(1), priority="high")
    await _add(USER, "übermorgen", due_date=_iso(2))
    await agent.add_items(make_ctx(USER, confirmed=True), {"items": "überfällig", "due_date": _iso(-1)})
    q = await agent.query_items(ctx, {})
    assert _titles(q) == ["überfällig", "morgen wichtig", "morgen normal", "übermorgen", "ohne Datum"]
    assert q["items"][0]["overdue"]


async def test_range_deadlines_overdue_search_count():
    await _add(USER, "A", due_date=_iso(1))
    await _add(USER, "B", deadline_date=_iso(1))
    await _add(USER, "C", deadline_date=_iso(20))
    await agent.add_items(make_ctx(USER, confirmed=True), {"items": "D", "deadline_date": _iso(-3)})
    q = await agent.query_items(make_ctx(USER), {"range": "tomorrow"})
    assert sorted(_titles(q)) == ["A", "B"]
    q = await agent.query_items(make_ctx(USER), {"range": "tomorrow", "only_deadlines": True})
    assert _titles(q) == ["B"]
    q = await agent.query_items(make_ctx(USER), {"range": "overdue"})
    assert _titles(q) == ["D"]
    await _add(USER, "Butter", list="Einkaufsliste")
    q = await agent.query_items(make_ctx(USER), {"list": "Einkaufsliste", "search": "Butter"})
    assert q["found"] and q["mode"] == "search"
    q = await agent.query_items(make_ctx(USER), {"list": "Einkaufsliste", "search": "Käse"})
    assert not q["found"]
    q = await agent.query_items(make_ctx(USER), {"list": "Meine Aufgaben", "count_only": True})
    assert q["total"] == 4 and q["mode"] == "count"


async def test_list_name_shown_only_for_multiple_lists():
    await _add(USER, "Milch", list="Einkaufsliste")
    await _add(USER, "Bericht")
    q = await agent.query_items(make_ctx(USER), {})
    assert all("list" in i for i in q["items"])
    q = await agent.query_items(make_ctx(USER), {"list": "Einkaufsliste"})
    assert all("list" not in i for i in q["items"])


async def test_voice_limit_and_chat_truncation():
    await _add(USER, ", ".join(f"E{i}" for i in range(8)), list="Einkaufsliste")
    q = await agent.query_items(make_ctx(USER, channel="voice"), {"list": "Einkaufsliste"})
    assert len(q["items"]) == 5 and q["remaining"] == 3
    q = await agent.query_items(make_ctx(USER), {"list": "Einkaufsliste"})
    assert len(q["items"]) == 8 and not q["truncated"]


async def test_notes_only_on_request():
    await _add(USER, "Arzt", note="Versichertenkarte mitnehmen")
    q = await agent.query_items(make_ctx(USER), {})
    assert "note" not in q["items"][0]
    q = await agent.query_items(make_ctx(USER), {"include_notes": True})
    assert q["items"][0]["note"] == "Versichertenkarte mitnehmen"


async def test_unknown_list_in_query():
    q = await agent.query_items(make_ctx(USER), {"list": "Werkstatt"})
    assert q["status"] == "list_not_found"


# ---------------------------------------------------------------------------
# Complete / reopen / update
# ---------------------------------------------------------------------------
async def test_complete_reopen_already_and_not_found():
    await _add(USER, "Reifen wechseln")
    r = await agent.complete_items(make_ctx(USER), {"items": "Reifen wechseln"})
    assert r["status"] == "completed" and _titles(r) == ["Reifen wechseln"]
    r = await agent.complete_items(make_ctx(USER), {"items": "Reifen wechseln und Fenster putzen"})
    assert r["already"] == ["Reifen wechseln"] and r["not_found"] == ["Fenster putzen"]
    assert (await agent.query_items(make_ctx(USER), {}))["total"] == 0
    r = await agent.reopen_items(make_ctx(USER), {"items": "Reifen wechseln"})
    assert r["status"] == "reopened" and _titles(r) == ["Reifen wechseln"]
    r = await agent.reopen_items(make_ctx(USER), {"items": "Reifen wechseln"})
    assert r["already"] == ["Reifen wechseln"]


async def test_done_query_records_who_and_when(pool):
    await _add(USER, "Milch", list="Einkaufsliste")
    await agent.complete_items(make_ctx(USER2), {"items": "Milch"})
    row = await pool.fetchrow("SELECT done_by::text, done_at FROM alice.list_items WHERE title = 'Milch'")
    assert row["done_by"] == USER2 and row["done_at"] is not None
    q = await agent.query_items(make_ctx(USER2), {"done": True, "range": "this_week"})
    assert _titles(q) == ["Milch"]
    q = await agent.query_items(make_ctx(USER), {"done": True})
    assert q["total"] == 0                                  # not done by USER
    q = await agent.query_items(make_ctx(USER), {"done": True, "list": "Einkaufsliste"})
    assert _titles(q) == ["Milch"]


async def test_same_title_in_two_lists_asks_with_list_names():
    await agent.manage_list(make_ctx(USER), {"action": "create", "name": "Baumarkt"})
    await _add(USER, "Farbe", list="Baumarkt")
    await _add(USER, "Farbe", list="Einkaufsliste")
    r = await agent.complete_items(make_ctx(USER), {"items": "Farbe"})
    assert r["status"] == "ambiguous"
    assert {c["list"] for c in r["candidates"]} == {"Baumarkt", "Einkaufsliste"}
    r = await agent.complete_items(make_ctx(USER), {"item_ref": r["candidates"][0]["item_ref"]})
    assert r["status"] == "completed" and len(r["items"]) == 1


async def test_update_fields_and_move():
    await _add(USER, "Reifen wechseln", due_date=_iso(1), due_time="14:00")
    r = await agent.update_item(make_ctx(USER), {"item": "Reifen", "new_due_time": "16:00", "new_priority": "high"})
    assert r["status"] == "updated"
    assert r["item"]["due"] == {"date": _iso(1), "time": "16:00"} and r["item"]["priority"] == "high"
    r = await agent.update_item(make_ctx(USER), {"item": "Reifen wechseln", "clear_due": True,
                                                 "new_title": "Winterreifen", "new_note": "Termin beim Händler"})
    assert "due" not in r["item"] and r["item"]["title"] == "Winterreifen" and r["item"]["note"]
    await agent.manage_list(make_ctx(USER), {"action": "create", "name": "Auto"})
    r = await agent.update_item(make_ctx(USER), {"item": "Winterreifen", "new_list": "Auto"})
    assert r["list"]["name"] == "Auto"
    q = await agent.update_item(make_ctx(USER), {"item": "Winterreifen", "new_deadline_date": _iso(-1)})
    assert q["status"] == "confirm_past"
    r = await agent.update_item(make_ctx(USER), {"item": "gibt es nicht", "new_title": "x"})
    assert r["status"] == "not_found"


async def test_child_cannot_update_shared_but_own_private():
    await _add(USER, "Milch", list="Einkaufsliste")
    r = await agent.update_item(make_ctx(CHILD), {"item": "Milch", "new_title": "Hafermilch"})
    assert r["error"] == "forbidden"
    await _add(CHILD, "Hausaufgaben")
    r = await agent.update_item(make_ctx(CHILD), {"item": "Hausaufgaben", "new_priority": "high"})
    assert r["status"] == "updated"


# ---------------------------------------------------------------------------
# Delete (two-stage outside the shopping list)
# ---------------------------------------------------------------------------
async def test_delete_needs_confirmation_next_turn():
    await _add(USER, "Reifen wechseln")
    q = await agent.remove_items(make_ctx(USER, turn=3), {"items": "Reifen wechseln"})
    assert q["status"] == "confirm_delete" and q["item"]["title"] == "Reifen wechseln"
    same = await agent.confirm_delete(make_ctx(USER, turn=3), {"ticket": q["ticket"]})
    assert same["error"] == "ticket_same_turn"
    r = await agent.confirm_delete(make_ctx(USER, turn=4), {"ticket": q["ticket"]})
    assert r["status"] == "deleted" and r["item"]["title"] == "Reifen wechseln"
    assert (await agent.query_items(make_ctx(USER), {}))["total"] == 0


async def test_unanswered_question_expires():
    await _add(USER, "Reifen wechseln")
    q = await agent.remove_items(make_ctx(USER, turn=3), {"items": "Reifen wechseln"})
    r = await agent.confirm_delete(make_ctx(USER, turn=5), {"ticket": q["ticket"]})
    assert r["error"] == "ticket_expired"
    assert (await agent.query_items(make_ctx(USER), {}))["total"] == 1


async def test_ticket_bound_to_user_and_session():
    await _add(USER, "Reifen wechseln")
    q = await agent.remove_items(make_ctx(USER, turn=3), {"items": "Reifen wechseln"})
    r = await agent.confirm_delete(make_ctx(USER2, turn=4), {"ticket": q["ticket"]})
    assert r["error"] == "ticket_wrong_owner"
    r = await agent.confirm_delete(make_ctx(USER, turn=4, session="other"), {"ticket": q["ticket"]})
    assert r["error"] == "ticket_wrong_owner"


async def test_changed_or_gone_item_is_not_deleted(pool):
    await _add(USER, "Reifen wechseln")
    q = await agent.remove_items(make_ctx(USER, turn=3), {"items": "Reifen wechseln"})
    await agent.update_item(make_ctx(USER), {"item": "Reifen wechseln", "new_priority": "high"})
    r = await agent.confirm_delete(make_ctx(USER, turn=4), {"ticket": q["ticket"]})
    assert r["error"] == "item_changed"
    q = await agent.remove_items(make_ctx(USER, turn=5), {"items": "Reifen wechseln"})
    await pool.execute("DELETE FROM alice.list_items WHERE title = 'Reifen wechseln'")
    r = await agent.confirm_delete(make_ctx(USER, turn=6), {"ticket": q["ticket"]})
    assert r["error"] == "item_gone"


async def test_multi_delete_outside_shopping_one_per_question():
    await _add(USER, "Fenster putzen, Rasen mähen")
    q = await agent.remove_items(make_ctx(USER, turn=1), {"items": "Fenster putzen und Rasen mähen"})
    assert q["status"] == "confirm_delete" and q["item"]["title"] == "Fenster putzen"
    assert q["deferred"] == ["Rasen mähen"]


async def test_cleanup_removes_done_only():
    await _add(USER, "Milch, Butter", list="Einkaufsliste")
    await agent.complete_items(make_ctx(USER), {"items": "Milch"})
    r = await agent.cleanup_list(make_ctx(USER), {"list": "Einkaufsliste"})
    assert r["status"] == "cleaned" and r["count"] == 1
    q = await agent.query_items(make_ctx(USER), {"list": "Einkaufsliste"})
    assert _titles(q) == ["Butter"]


async def test_purge_after_30_days(pool):
    await _add(USER, "alt, neu", list="Einkaufsliste")
    await agent.complete_items(make_ctx(USER), {"items": "alt, neu"})
    await pool.execute("UPDATE alice.list_items SET done_at = NOW() - interval '31 days' WHERE title = 'alt'")
    assert await db.purge_done(30) >= 1
    titles = [r["title"] for r in await pool.fetch("SELECT title FROM alice.list_items")]
    assert titles == ["neu"]


# ---------------------------------------------------------------------------
# Permissions per role
# ---------------------------------------------------------------------------
async def test_role_flag_and_revocation(pool):
    assert await db.caller_access(USER) == ("user", True)
    assert await db.caller_access(CHILD) == ("child", True)
    assert (await db.caller_access("b0000000-0000-0000-0000-00000000000e"))[1] is False   # guest
    await db.set_role_config([{"role": "child", "can_use_lists": False}])
    assert await db.caller_access(CHILD) == ("child", False)
    assert await db.caller_access("00000000-0000-0000-0000-000000000000") == (None, False)


async def test_concurrent_complete_reports_already_done():
    await _add(USER, "Milch", list="Einkaufsliste")
    r1 = await agent.complete_items(make_ctx(USER), {"items": "Milch"})
    r2 = await agent.complete_items(make_ctx(USER2), {"items": "Milch"})
    assert _titles(r1) == ["Milch"] and r2["already"] == ["Milch"]


async def test_latency_reasonable():
    await _add(USER, ", ".join(f"E{i}" for i in range(20)), list="Einkaufsliste")
    t0 = time.monotonic()
    await agent.query_items(make_ctx(USER), {})
    assert time.monotonic() - t0 < 1.0
