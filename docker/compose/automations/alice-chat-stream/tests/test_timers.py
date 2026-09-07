"""PROJ-85 — Timer-Agent unit tests.

Pure parsing helpers plus the handler driven against an in-memory fake pool.
conftest.py stubs httpx/asyncpg, so no real DB / HA is touched.
"""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import timers
from app.timers import (
    derived_name,
    parse_delta,
    parse_name,
    parse_ref_name,
    parse_time,
    timer_action,
    wants_all,
)

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 7, 14, 0, 0, tzinfo=TZ)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# parse_time — duration
# ---------------------------------------------------------------------------
class TestParseDuration:
    def test_minutes(self):
        p = parse_time("Setze einen Timer auf 20 Minuten", now=NOW)
        assert p.seconds == 1200
        assert p.spoken_duration == "20 Minuten"
        assert not p.is_clock

    def test_hours_and_minutes(self):
        p = parse_time("Timer auf 1 Stunde 30 Minuten", now=NOW)
        assert p.seconds == 5400
        assert p.spoken_duration == "1 Stunde 30 Minuten"

    def test_one_minute_singular(self):
        p = parse_time("Timer auf 1 Minute", now=NOW)
        assert p.seconds == 60
        assert p.spoken_duration == "1 Minute"

    def test_decimal_minutes_converted(self):
        p = parse_time("Timer auf 2,5 Minuten", now=NOW)
        assert p.seconds == 150
        assert p.spoken_duration == "2 Minuten 30 Sekunden"

    def test_seconds(self):
        p = parse_time("Timer auf 90 Sekunden", now=NOW)
        assert p.seconds == 90

    def test_no_time(self):
        assert parse_time("Setze einen Timer", now=NOW).seconds is None

    def test_bare_number_reads_as_minutes(self):
        # sentence-splitter leaves "Setze einen Timer auf 10" for the first half
        p = parse_time("Setze einen Timer auf 10", now=NOW)
        assert p.seconds == 600
        assert not p.is_clock

    def test_out_of_range_unit_rejected(self):
        # BUG-2: "3 Wochen" must not be misread as 3 minutes
        for s in ("einen auf 3 Wochen", "Timer auf 2 Tage", "einen auf 1 Monat"):
            p = parse_time(s, now=NOW)
            assert p.rejected is True
            assert p.seconds is None

    def test_duration_beats_clock_wording(self):
        # "20 Minuten" must never be read as a clock
        p = parse_time("Stelle einen Timer auf 20 Minuten", now=NOW)
        assert not p.is_clock


# ---------------------------------------------------------------------------
# parse_time — absolute clock
# ---------------------------------------------------------------------------
class TestParseClock:
    def test_future_today(self):
        p = parse_time("Stelle einen Timer auf 15 Uhr 40", now=NOW)
        assert p.is_clock
        assert p.clock == "15 Uhr 40"
        assert p.seconds == 100 * 60  # 14:00 -> 15:40

    def test_past_today_rolls_to_tomorrow(self):
        p = parse_time("Timer auf 8 Uhr", now=NOW)
        assert p.is_clock
        assert p.seconds == (18 * 3600)  # 14:00 -> next 08:00

    def test_exact_now_is_tomorrow(self):
        p = parse_time("Timer auf 14 Uhr", now=NOW)
        assert p.seconds == 24 * 3600

    def test_no_minutes_means_zero(self):
        p = parse_time("Timer auf 15 Uhr", now=NOW)
        assert p.clock == "15 Uhr"
        assert p.seconds == 3600

    def test_ambiguous_4_uhr_at_night_next_occurrence(self):
        night = datetime(2026, 9, 7, 22, 0, 0, tzinfo=TZ)
        p = parse_time("Timer auf 4 Uhr", now=night)
        assert p.seconds == 6 * 3600  # 22:00 -> 04:00 next day


# ---------------------------------------------------------------------------
# names / delta / all
# ---------------------------------------------------------------------------
class TestNames:
    def test_explicit_name_singularised(self):
        assert parse_name("Stelle einen Timer für Kartoffeln auf 20 Minuten") == "Kartoffel"

    def test_explicit_name_plain(self):
        assert parse_name("Timer für Tee auf 5 Minuten") == "Tee"

    def test_no_name(self):
        assert parse_name("Setze einen Timer auf 20 Minuten") is None

    def test_derived_name_duration(self):
        p = parse_time("Timer auf 20 Minuten", now=NOW)
        assert derived_name(p) == "20 Minuten Timer"

    def test_derived_name_clock(self):
        p = parse_time("Timer auf 15 Uhr 40", now=NOW)
        assert derived_name(p) == "15 Uhr 40 Timer"

    def test_ref_name(self):
        assert parse_ref_name("Verlängere den Kartoffel Timer um 5 Minuten") == "Kartoffel"

    def test_ref_name_absent(self):
        assert parse_ref_name("Wie lange läuft der Timer noch") is None

    def test_ref_name_derived_digit_start(self):
        # BUG-1: derived names begin with a digit
        assert parse_ref_name("Verlängere den 20 Minuten Timer um 5 Minuten") == "20 Minuten"
        assert parse_ref_name("Wie lange läuft der 15 Uhr 40 Timer noch") == "15 Uhr 40"

    def test_delta(self):
        assert parse_delta("Verlängere den Timer um 5 Minuten") == 300

    def test_delta_absent(self):
        assert parse_delta("Verlängere den Timer") is None

    def test_wants_all(self):
        assert wants_all("Lösche alle Timer")
        assert not wants_all("Lösche den Kartoffel Timer")


# ---------------------------------------------------------------------------
# timer_action mapping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("service,expected", [
    ("timer.set", "set"),
    ("timer.extend", "extend"),
    ("timer.delete", "delete"),
    ("light.turn_on", None),
    (None, None),
])
def test_timer_action(service, expected):
    assert timer_action(service, None) == expected


def test_timer_action_from_template():
    assert timer_action(None, "timer:query") == "query"


# ---------------------------------------------------------------------------
# Fake pool — enough of the asyncpg surface for the handler
# ---------------------------------------------------------------------------
class FakeConn:
    def __init__(self, store):
        self.store = store

    def transaction(self):
        conn = self

        class _T:
            async def __aenter__(self_):
                return conn

            async def __aexit__(self_, *a):
                return False

        return _T()

    async def fetchrow(self, sql, *args):
        return await self.store.fetchrow(sql, *args)

    async def fetch(self, sql, *args):
        return await self.store.fetch(sql, *args)

    async def execute(self, sql, *args):
        return await self.store.execute(sql, *args)


class FakePool:
    """Minimal in-memory alice.timers + role config."""

    def __init__(self, *, role="admin", default_role="user", allowed=True,
                 max_active=20, max_duration=86400, timers_rows=None, user_role=None):
        self._role = role
        self._default_role = default_role
        self._allowed = allowed
        self._max_active = max_active
        self._max_duration = max_duration
        self.rows = list(timers_rows or [])
        self._user_role = user_role or role
        self._id = 0

    def acquire(self):
        pool = self

        class _Acq:
            async def __aenter__(self_):
                return FakeConn(pool)

            async def __aexit__(self_, *a):
                return False

        return _Acq()

    def _norm(self, sql):
        return " ".join(sql.split())

    async def fetchrow(self, sql, *args):
        s = self._norm(sql)
        if "FROM alice.users WHERE id" in s:
            return {"role": self._user_role}
        if "timer_default_role" in s:
            return {"value": f'"{self._default_role}"'}
        if "assistant_permissions FROM alice.role_templates" in s:
            return {"assistant_permissions": {
                "can_use_timers": self._allowed,
                "timer_max_active": self._max_active,
                "timer_max_duration_seconds": self._max_duration,
            }}
        if "COUNT(*) AS c FROM alice.timers" in s:
            role = args[0]
            statuses = args[1]
            c = sum(1 for r in self.rows if r["owner_role"] == role and r["status"] in statuses)
            return {"c": c}
        if s.startswith("SELECT 1 FROM alice.timers"):
            role, statuses, name = args
            hit = any(
                r["owner_role"] == role and r["status"] in statuses
                and r["name"].lower() == name.lower()
                for r in self.rows
            )
            return {"1": 1} if hit else None
        if "INSERT INTO alice.timers" in s:
            self._id += 1
            row = {
                "id": f"tid-{self._id}",
                "owner_user_id": args[0], "owner_role": args[1], "name": args[2],
                "expires_at": args[3], "status": "running", "origin_channel": args[4],
                "paused_remaining_seconds": None,
            }
            self.rows.append(row)
            return {"id": row["id"], "name": row["name"], "expires_at": row["expires_at"],
                    "status": "running"}
        if "SELECT id, name, expires_at FROM alice.timers" in s and "FOR UPDATE" in s:
            tid = args[0]
            for r in self.rows:
                if r["id"] == tid and r["status"] == "running":
                    return {"id": r["id"], "name": r["name"], "expires_at": r["expires_at"]}
            return None
        if "SELECT id, name, expires_at, status FROM alice.timers" in s and "FOR UPDATE" in s:
            tid = args[0]
            for r in self.rows:
                if r["id"] == tid:
                    return dict(r)
            return None
        if "SELECT id, name, status, paused_remaining_seconds FROM alice.timers" in s and "FOR UPDATE" in s:
            tid = args[0]
            for r in self.rows:
                if r["id"] == tid:
                    return dict(r)
            return None
        if "SELECT id, name, status, origin_channel FROM alice.timers" in s and "FOR UPDATE" in s:
            tid = args[0]
            for r in self.rows:
                if r["id"] == tid:
                    return dict(r)
            return None
        if "UPDATE alice.timers SET expires_at" in s and "RETURNING" in s:
            tid, new_expiry = args
            for r in self.rows:
                if r["id"] == tid:
                    r["expires_at"] = new_expiry
                    return {"id": r["id"], "name": r["name"], "expires_at": new_expiry}
            return None
        if "DELETE FROM alice.timers" in s and "RETURNING 1" in s:
            role, statuses = args
            before = len(self.rows)
            self.rows = [
                r for r in self.rows
                if not (r["owner_role"] == role and r["status"] in statuses)
            ]
            return {"c": before - len(self.rows)}
        return None

    async def fetch(self, sql, *args):
        s = self._norm(sql)
        if "ORDER BY expires_at ASC" in s:
            role, statuses = args
            return [
                r for r in sorted(self.rows, key=lambda x: x["expires_at"])
                if r["owner_role"] == role and r["status"] in statuses
            ]
        if "LOWER(name) = $3 OR LOWER(name) = $3" in s:
            role, statuses, n = args
            return [
                r for r in self.rows
                if r["owner_role"] == role and r["status"] in statuses
                and (r["name"].lower() == n or r["name"].lower() == f"{n} timer")
            ]
        return []

    async def execute(self, sql, *args):
        s = self._norm(sql)
        if "SET paused_remaining_seconds = $2" in s and "status" not in s.split("SET")[1].split("WHERE")[0]:
            tid, rem = args
            for r in self.rows:
                if r["id"] == tid:
                    r["paused_remaining_seconds"] = rem
            return "UPDATE 1"
        if "SET status = 'paused'" in s:
            tid, rem = args
            for r in self.rows:
                if r["id"] == tid:
                    r["status"] = "paused"
                    r["paused_remaining_seconds"] = rem
            return "UPDATE 1"
        if "SET status = 'running'" in s:
            tid, new_expiry = args
            for r in self.rows:
                if r["id"] == tid:
                    r["status"] = "running"
                    r["paused_remaining_seconds"] = None
                    r["expires_at"] = new_expiry
            return "UPDATE 1"
        if "DELETE FROM alice.timers WHERE id" in s:
            tid = args[0]
            self.rows = [r for r in self.rows if r["id"] != tid]
            return "DELETE 1"
        return "OK"


def _mk_row(**kw):
    base = {
        "id": "seed-1", "owner_user_id": None, "owner_role": "admin",
        "name": "20 Minuten Timer", "status": "running",
        "expires_at": NOW + timedelta(minutes=20),
        "paused_remaining_seconds": None, "origin_channel": "webapp",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# handle_timer_part — set
# ---------------------------------------------------------------------------
class TestHandleSet:
    def test_set_duration(self):
        pool = FakePool()
        r = run(timers.handle_timer_part(
            pool, "Setze einen Timer auf 20 Minuten", "set",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "20 Minuten" in r.text
        assert r.created is not None
        assert len(pool.rows) == 1
        assert pool.rows[0]["name"] == "20 Minuten Timer"

    def test_set_clock_includes_runtime(self):
        pool = FakePool()
        r = run(timers.handle_timer_part(
            pool, "Stelle einen Timer auf 15 Uhr 40", "set",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "15 Uhr 40" in r.text
        assert "er läuft" in r.text

    def test_set_named(self):
        pool = FakePool()
        r = run(timers.handle_timer_part(
            pool, "Stelle einen Timer für Kartoffeln auf 20 Minuten", "set",
            user_id="u1", source="esphome:Küche", now=NOW,
        ))
        assert "Kartoffel Timer" in r.text
        assert pool.rows[0]["origin_channel"] == "esphome:Küche"

    def test_min_duration_rejected(self):
        pool = FakePool()
        r = run(timers.handle_timer_part(
            pool, "Timer auf 5 Sekunden", "set", user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "mindestens" in r.text
        assert pool.rows == []

    def test_max_duration_rejected(self):
        pool = FakePool(max_duration=7200)  # child-like 2 h
        r = run(timers.handle_timer_part(
            pool, "Timer auf 5 Stunden", "set", user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "höchstens" in r.text
        assert pool.rows == []

    def test_max_active_rejected(self):
        pool = FakePool(max_active=1, timers_rows=[_mk_row()])
        r = run(timers.handle_timer_part(
            pool, "Timer auf 10 Minuten", "set", user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "höchstens 1 Timer" in r.text

    def test_name_collision_fallback(self):
        pool = FakePool(timers_rows=[_mk_row(name="20 Minuten Timer")])
        r = run(timers.handle_timer_part(
            pool, "Timer auf 20 Minuten", "set", user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "zweiter 20 Minuten Timer" in r.text

    def test_no_time_asks(self):
        pool = FakePool()
        r = run(timers.handle_timer_part(
            pool, "Setze einen Timer", "set", user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "wie viele minuten" in r.text.lower()
        assert pool.rows == []

    def test_role_not_allowed(self):
        pool = FakePool(allowed=False)
        r = run(timers.handle_timer_part(
            pool, "Timer auf 10 Minuten", "set", user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "nicht freigeschaltet" in r.text
        assert pool.rows == []

    def test_unknown_speaker_uses_default_role(self):
        pool = FakePool(default_role="admin")
        run(timers.handle_timer_part(
            pool, "Timer auf 10 Minuten", "set",
            user_id="00000000-0000-0000-0000-000000000000",
            source="esphome:Küche", now=NOW,
        ))
        assert pool.rows[0]["owner_role"] == "admin"
        assert pool.rows[0]["owner_user_id"] is None


# ---------------------------------------------------------------------------
# handle_timer_part — change / query / pause / delete
# ---------------------------------------------------------------------------
class TestHandleChange:
    def test_extend(self):
        pool = FakePool(timers_rows=[_mk_row(id="t1", name="Kartoffel Timer")])
        r = run(timers.handle_timer_part(
            pool, "Verlängere den Kartoffel Timer um 5 Minuten", "extend",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "läuft jetzt noch" in r.text
        assert pool.rows[0]["expires_at"] == NOW + timedelta(minutes=25)

    def test_shorten_too_much_rejected(self):
        pool = FakePool(timers_rows=[_mk_row(id="t1", name="Kartoffel Timer",
                                             expires_at=NOW + timedelta(minutes=12))])
        r = run(timers.handle_timer_part(
            pool, "Verkürze den Kartoffel Timer um 30 Minuten", "shorten",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "nicht abziehen" in r.text
        assert pool.rows[0]["expires_at"] == NOW + timedelta(minutes=12)

    def test_change_no_name_single_timer(self):
        pool = FakePool(timers_rows=[_mk_row(id="t1")])
        r = run(timers.handle_timer_part(
            pool, "Verlängere den Timer um 2 Minuten", "extend",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "läuft jetzt noch" in r.text

    def test_change_no_name_multiple_asks(self):
        pool = FakePool(timers_rows=[_mk_row(id="t1", name="A Timer"),
                                     _mk_row(id="t2", name="B Timer")])
        r = run(timers.handle_timer_part(
            pool, "Verlängere den Timer um 2 Minuten", "extend",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "mehrere Timer" in r.text.lower() or "welchen" in r.text.lower()

    def test_unknown_name(self):
        pool = FakePool(timers_rows=[_mk_row(id="t1", name="Kartoffel Timer")])
        r = run(timers.handle_timer_part(
            pool, "Verlängere den Nudel Timer um 5 Minuten", "extend",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "keinen Nudel Timer" in r.text

    def test_query_list(self):
        pool = FakePool(timers_rows=[_mk_row(id="t1", name="Kartoffel Timer")])
        r = run(timers.handle_timer_part(
            pool, "Welche Timer laufen gerade", "query",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "Kartoffel Timer" in r.text

    def test_query_empty(self):
        pool = FakePool()
        r = run(timers.handle_timer_part(
            pool, "Welche Timer laufen gerade", "query",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "kein Timer" in r.text

    def test_pause_then_resume(self):
        pool = FakePool(timers_rows=[_mk_row(id="t1", name="Kartoffel Timer")])
        r1 = run(timers.handle_timer_part(
            pool, "Pausiere den Kartoffel Timer", "pause",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "pausiert" in r1.text
        assert pool.rows[0]["status"] == "paused"
        r2 = run(timers.handle_timer_part(
            pool, "Setze den Kartoffel Timer fort", "resume",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "läuft weiter" in r2.text
        assert pool.rows[0]["status"] == "running"

    def test_delete_one(self):
        pool = FakePool(timers_rows=[_mk_row(id="t1", name="Kartoffel Timer")])
        r = run(timers.handle_timer_part(
            pool, "Lösche den Kartoffel Timer", "delete",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "gelöscht" in r.text
        assert pool.rows == []

    def test_delete_all(self):
        pool = FakePool(timers_rows=[_mk_row(id="t1", name="A Timer"),
                                     _mk_row(id="t2", name="B Timer")])
        r = run(timers.handle_timer_part(
            pool, "Lösche alle Timer", "delete",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "2 Timer" in r.text
        assert pool.rows == []

    def test_extend_derived_name_with_multiple_timers(self):
        # BUG-1: "den 20 Minuten Timer" must disambiguate even with several timers
        pool = FakePool(timers_rows=[
            _mk_row(id="t1", name="20 Minuten Timer"),
            _mk_row(id="t2", name="Kartoffel Timer"),
        ])
        r = run(timers.handle_timer_part(
            pool, "Verlängere den 20 Minuten Timer um 5 Minuten", "extend",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "läuft jetzt noch" in r.text
        assert pool.rows[0]["expires_at"] == NOW + timedelta(minutes=25)

    def test_set_out_of_range_unit_rejected(self):
        # BUG-2
        pool = FakePool()
        r = run(timers.handle_timer_part(
            pool, "Timer auf 3 Wochen", "set",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "So lange kann ich keinen Timer stellen" in r.text
        assert pool.rows == []

    def test_extend_paused_timer(self):
        # BUG-3: extending a paused timer adjusts its frozen remaining
        pool = FakePool(timers_rows=[_mk_row(
            id="t1", name="Kartoffel Timer", status="paused",
            paused_remaining_seconds=600,
        )])
        r = run(timers.handle_timer_part(
            pool, "Verlängere den Kartoffel Timer um 5 Minuten", "extend",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "pausiert" in r.text
        assert pool.rows[0]["paused_remaining_seconds"] == 900

    def test_cleanup_allowed_after_permission_lost(self):
        # BUG-6: role lost the permission but can still query + delete
        pool = FakePool(allowed=False, timers_rows=[_mk_row(id="t1", name="A Timer")])
        q = run(timers.handle_timer_part(
            pool, "Welche Timer laufen gerade", "query",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "A Timer" in q.text
        d = run(timers.handle_timer_part(
            pool, "Lösche alle Timer", "delete",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "gelöscht" in d.text
        assert pool.rows == []
        # but setting is still blocked
        s = run(timers.handle_timer_part(
            pool, "Timer auf 10 Minuten", "set",
            user_id="u1", source="webapp_cc", now=NOW,
        ))
        assert "nicht freigeschaltet" in s.text
