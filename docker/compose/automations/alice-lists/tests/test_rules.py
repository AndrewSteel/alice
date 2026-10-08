"""Pure rules: multi-entry split, name / title matching, dates, permissions."""
from datetime import date, datetime, time, timedelta

import pytest

from app import agent
from app import textutil as tx
from app import timeutil as tu
from tests.conftest import TZ


# ---------------------------------------------------------------------------
# Split rule — every comma and every "und", without exception
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [
    ("Milch, Butter und Eier", ["Milch", "Butter", "Eier"]),
    ("Salz und Pfeffer", ["Salz", "Pfeffer"]),
    ("2 Packungen Milch und 6 Eier", ["2 Packungen Milch", "6 Eier"]),
    ("Butter", ["Butter"]),
    ("Milch,Butter , Eier.", ["Milch", "Butter", "Eier"]),
    ("„Brot“ und „Käse“", ["Brot", "Käse"]),
    ("Milch UND Brot", ["Milch", "Brot"]),
    ("und Eier", ["Eier"]),
    (["Milch", "Butter und Eier"], ["Milch", "Butter", "Eier"]),
    ("", []),
    (None, []),
    ("milk and bread", ["milk", "bread"]),
])
def test_split_items(raw, expected):
    assert tx.split_items(raw) == expected


def test_split_keeps_words_containing_und():
    assert tx.split_items("Hundefutter und Rundholz") == ["Hundefutter", "Rundholz"]


def test_long_entry_is_kept_whole():
    long = "einen großen Sack Kartoffeln für das Wochenende bei Oma " * 5
    assert tx.split_items(long) == [long.strip()]


@pytest.mark.parametrize("name", ["Einkaufsliste", "einkaufszettel", "die Einkaufsliste", "meine Einkaufsliste",
                                  "shopping list"])
def test_shopping_alias(name):
    assert tx.is_shopping_alias(name)


def test_not_shopping_alias():
    assert not tx.is_shopping_alias("Baumarkt")
    assert not tx.is_shopping_alias("Einkaufsliste Baumarkt")


def test_match_names_exact_and_approximate():
    names = ["Baumarkt", "Arbeit", "Urlaub", "Meine Aufgaben"]
    assert tx.match_names("Baumarktliste", names) == [0]
    assert tx.match_names("die Liste Urlaub", names) == [2]
    assert tx.match_names("arbeit", names) == [1]
    assert tx.match_names("Werkstatt", names) == []
    assert tx.match_names("meine aufgaben", names) == [3]


def test_match_names_prefers_exact():
    assert tx.match_names("Urlaub", ["Urlaub", "Urlaubsplanung"]) == [0]
    assert tx.match_names("Urlaub", ["Urlaub Italien", "Urlaub Spanien"]) == [0, 1]


def test_title_score():
    assert tx.title_score("Reifen wechseln", "Reifen wechseln") == 3
    assert tx.title_score("die Aufgabe Reifen wechseln", "Reifen wechseln") == 3
    assert tx.title_score("Reifen", "Reifen wechseln") == 2
    assert tx.title_score("Steuer", "Steuererklärung") == 2
    assert tx.title_score("Butter", "Milch") == 0
    assert tx.title_score("Reifen wechsel", "Reifen wechseln") >= 1


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
def test_time_without_date_today_or_tomorrow():
    now = datetime(2026, 10, 8, 10, 0, tzinfo=TZ)
    w = tu.build_when(None, time(14, 0), TZ, now)
    assert (w.at.date(), w.has_time) == (date(2026, 10, 8), True)
    w = tu.build_when(None, time(9, 0), TZ, now)
    assert w.at.date() == date(2026, 10, 9)


def test_date_only_is_local_midnight_and_not_past_today():
    now = datetime(2026, 10, 8, 23, 0, tzinfo=TZ)
    w = tu.build_when(date(2026, 10, 8), None, TZ, now)
    assert not w.has_time and w.at.hour == 0
    assert not w.is_past(now, TZ)
    assert tu.build_when(date(2026, 10, 7), None, TZ, now).is_past(now, TZ)


def test_dst_switch_keeps_local_time():
    # 2026-10-25: CEST → CET
    w = tu.build_when(date(2026, 10, 25), time(14, 0), TZ, datetime(2026, 10, 1, tzinfo=TZ))
    assert w.at.astimezone(TZ).hour == 14
    assert tu.describe_when(w.at, True, TZ) == {"date": "2026-10-25", "time": "14:00"}


def test_parse_date_formats():
    assert tu.parse_date("2026-07-31") == date(2026, 7, 31)
    assert tu.parse_date("31.07.2026") == date(2026, 7, 31)
    with pytest.raises(tu.InputError):
        tu.parse_date("31. Juli")


def test_ranges_open_and_done():
    now = datetime(2026, 10, 8, 10, 0, tzinfo=TZ)  # Thursday
    r = tu.resolve_range("this_week", TZ, now)
    assert (r.first_day, r.last_day) == (date(2026, 10, 8), date(2026, 10, 11))
    r = tu.resolve_range("this_week", TZ, now, done=True)
    assert (r.first_day, r.last_day) == (date(2026, 10, 5), date(2026, 10, 8))
    r = tu.resolve_range(None, TZ, now, done=True)
    assert r.first_day == date(2026, 10, 8) - timedelta(days=30)
    assert tu.resolve_range("overdue", TZ, now).first_day is None
    with pytest.raises(tu.InputError):
        tu.resolve_range("someday", TZ, now)


# ---------------------------------------------------------------------------
# Permission matrix
# ---------------------------------------------------------------------------
SHARED = {"is_shared": True, "is_shopping": False, "owner_id": None, "created_by": "creator"}
SHOP = {"is_shared": True, "is_shopping": True, "owner_id": None, "created_by": None}
PRIV = {"is_shared": False, "is_shopping": False, "owner_id": "me", "created_by": "me"}


def _ctx(user_id, role):
    return agent.Ctx(user_id=user_id, role=role, tz=TZ, now=datetime.now(TZ))


@pytest.mark.parametrize("role, action, lst, allowed", [
    ("child", "read", SHARED, True), ("child", "add", SHOP, True), ("child", "complete", SHOP, True),
    ("child", "remove", SHOP, False), ("child", "update", SHARED, False), ("child", "cleanup", SHARED, False),
    ("child", "create_shared", None, False), ("child", "delete", SHARED, False),
    ("child", "remove", PRIV, True), ("child", "delete", PRIV, True),
    ("user", "remove", SHOP, True), ("user", "create_shared", None, True), ("user", "flag_shopping", SHARED, False),
    ("user", "delete", SHARED, False), ("user", "rename", SHARED, False), ("user", "delete", SHOP, False),
    ("admin", "delete", SHOP, True), ("admin", "flag_shopping", SHARED, True), ("admin", "rename", SHARED, True),
])
def test_permission_matrix(role, action, lst, allowed):
    assert (agent.permission_error(_ctx("me", role), action, lst) is None) == allowed


def test_creator_may_manage_own_shared_list():
    ctx = _ctx("creator", "user")
    assert agent.permission_error(ctx, "rename", SHARED) is None
    assert agent.permission_error(ctx, "delete", SHARED) is None


def test_child_remove_from_shopping_hint():
    assert agent.permission_error(_ctx("me", "child"), "remove", SHOP)["error"] == "forbidden_child_remove"


def test_unknown_speaker_only_adds_to_shopping():
    ctx = agent.Ctx(user_id=None, role=None, tz=TZ, now=datetime.now(TZ))
    assert agent.permission_error(ctx, "add", SHOP) is None
    for action, lst in (("read", SHOP), ("complete", SHOP), ("remove", SHOP), ("add", SHARED), ("add", None)):
        assert agent.permission_error(ctx, action, lst)["error"] == "unknown_speaker"


def test_private_list_of_someone_else_is_forbidden_even_for_admin():
    assert agent.permission_error(_ctx("admin-id", "admin"), "read", PRIV)["error"] == "forbidden"
