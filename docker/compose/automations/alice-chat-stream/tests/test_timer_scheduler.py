"""PROJ-85 — timer scheduler: due-claim idempotency, house-wide alarm session
(Refinement 2026-10-15), atomic voice announcement, WebApp acknowledgement,
media_player list from device-mapping.yaml."""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import timer_scheduler, timers
from app.timer_scheduler import TimerScheduler, pending_announcement

TZ = ZoneInfo("Europe/Berlin")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _now():
    return datetime.now(TZ)


class FakePool:
    """In-memory stand-in for alice.timers, interpreting the scheduler's SQL."""

    def __init__(self, rows):
        self.rows = rows

    @staticmethod
    def _n(sql):
        return " ".join(sql.split())

    def _cutoff(self, secs):
        return _now() - timedelta(seconds=secs)

    async def fetchrow(self, sql, *a):
        s = self._n(sql)
        if "MIN(expires_at)" in s:
            running = [r["expires_at"] for r in self.rows if r["status"] == "running"]
            return {"next": min(running) if running else None}
        if s.startswith("SELECT 1 FROM alice.timers WHERE status = 'expired'"):
            cutoff = self._cutoff(a[0])
            hit = [r for r in self.rows
                   if r["status"] == "expired" and r["fired_at"] >= cutoff]
            return {"?column?": 1} if hit else None
        if "acknowledged_by = 'webapp'" in s:  # timers.acknowledge_webapp
            ids, role = set(a[0]), a[1]
            n = 0
            for r in self.rows:
                early = _now() + timedelta(seconds=a[2])
                if (r["id"] in ids and r["owner_role"] == role and (
                        r["status"] == "expired"
                        or (r["status"] == "acknowledged" and r["acknowledged_by"] == "timeout")
                        or (r["status"] == "running" and r["expires_at"] <= early))):
                    r["status"], r["acknowledged_by"] = "acknowledged", "webapp"
                    r["fired_at"] = r["fired_at"] or _now()
                    n += 1
            return {"c": n}
        return None

    async def fetch(self, sql, *a):
        s = self._n(sql)
        if s.startswith("UPDATE alice.timers SET status = 'expired'"):
            cutoff = _now() + timedelta(seconds=a[0])
            claimed = []
            for r in self.rows:
                if r["status"] == "running" and r["expires_at"] <= cutoff:
                    r["status"], r["fired_at"] = "expired", _now()
                    claimed.append({k: r[k] for k in (
                        "id", "name", "expires_at", "origin_channel", "owner_role")})
            return claimed
        if "acknowledged_by = 'voice'" in s:  # pending_announcement claim
            cutoff = self._cutoff(a[0])
            out = []
            for r in self.rows:
                if r["status"] == "expired" and r["fired_at"] >= cutoff:
                    r["status"], r["acknowledged_by"] = "acknowledged", "voice"
                    out.append({"name": r["name"], "expires_at": r["expires_at"]})
            return out
        if "SELECT id FROM alice.timers" in s and "expires_at <= NOW()" in s:
            return [{"id": r["id"]} for r in self.rows
                    if r["status"] == "running" and r["expires_at"] <= _now()]
        if s.startswith("SELECT id, name, expires_at, fired_at FROM alice.timers"):
            role, cutoff = a[0], self._cutoff(a[1])
            return [r for r in self.rows
                    if r["owner_role"] == role and r["fired_at"] and r["fired_at"] >= cutoff
                    and (r["status"] == "expired"
                         or (r["status"] == "acknowledged" and r["acknowledged_by"] == "timeout"))]
        return []

    async def execute(self, sql, *a):
        s = self._n(sql)
        if "acknowledged_by = 'timeout'" in s and "fired_at <" in s:  # stale sweep
            cutoff = self._cutoff(a[0])
            for r in self.rows:
                if r["status"] == "expired" and r["fired_at"] < cutoff:
                    r["status"], r["acknowledged_by"] = "acknowledged", "timeout"
        elif "acknowledged_by = 'timeout'" in s:  # session auto-acknowledge
            ids = set(a[0])
            for r in self.rows:
                if r["id"] in ids and r["status"] == "expired":
                    r["status"], r["acknowledged_by"] = "acknowledged", "timeout"
        return "OK"


def _row(**kw):
    base = {
        "id": "r1", "name": "20 Minuten Timer", "status": "running",
        "expires_at": _now() - timedelta(seconds=1), "fired_at": None,
        "origin_channel": "webapp", "owner_role": "admin", "acknowledged_by": None,
    }
    base.update(kw)
    return base


def _expired(**kw):
    return _row(status="expired", fired_at=_now() - timedelta(seconds=5), **kw)


class FakeHA:
    """Records the HA script calls instead of hitting HA."""

    def __init__(self, fail=False):
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail
        self.unavailable: set[str] = set()
        ha = self

        class _Resp:
            status_code = 200

            def __init__(self_, state=None):
                self_._state = state

            def json(self_):
                return {"state": self_._state}

            def raise_for_status(self_):
                if ha.fail:
                    raise RuntimeError("HA unreachable")

        class _Client:
            def __init__(self_, *a, **kw):
                pass

            async def __aenter__(self_):
                return self_

            async def __aexit__(self_, *a):
                return False

            async def get(self_, url, headers=None):
                entity = url.rsplit("/", 1)[1]
                return _Resp("unavailable" if entity in ha.unavailable else "idle")

            async def post(self_, url, json=None, headers=None):
                ha.calls.append((json["entity_id"], json.get("variables", {})))
                return _Resp()

        self.client = _Client

    def scripts(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def ha(monkeypatch):
    fake = FakeHA()
    monkeypatch.setattr(timer_scheduler.httpx, "AsyncClient", fake.client)
    monkeypatch.setattr(timer_scheduler, "HA_TOKEN", "tok")
    monkeypatch.setattr(timer_scheduler, "all_media_players",
                        lambda: ["media_player.buero", "media_player.kueche"])
    return fake


START = timer_scheduler.HA_MELODY_START_SCRIPT
STOP = timer_scheduler.HA_MELODY_STOP_SCRIPT


def _sched(pool):
    return TimerScheduler(lambda: pool)


async def _fire(sched):
    await sched._fire_due()
    # the session auto-acknowledge task sleeps MELODY_MAX_SECONDS; cancel it
    if sched._session_task:
        sched._session_task.cancel()


# ---------------------------------------------------------------------------
# Claim + house-wide session
# ---------------------------------------------------------------------------
def test_fire_due_claims_once(ha):
    pool = FakePool([_row(id="r1")])
    sched = _sched(pool)
    run(_fire(sched))
    assert pool.rows[0]["status"] == "expired"
    run(_fire(sched))  # a second pass claims nothing new
    assert ha.scripts() == [START]


def test_alarm_rings_on_all_speakers_for_any_channel_and_role(ha):
    # Refinement 2026-10-15: a WebApp timer, a voice timer of another room and
    # a child timer share ONE melody on ALL speakers.
    pool = FakePool([
        _row(id="a", name="A Timer", origin_channel="webapp"),
        _row(id="b", name="B Timer", origin_channel="esphome:Küche"),
        _row(id="c", name="C Timer", origin_channel="esphome:Büro", owner_role="child"),
    ])
    sched = _sched(pool)
    run(_fire(sched))
    assert ha.calls == [(START, {
        "media_players": "media_player.buero,media_player.kueche",
        "max_seconds": timer_scheduler.MELODY_MAX_SECONDS,
    })]
    assert sched.alarm_active()
    assert sched._session_timer_ids == {"a", "b", "c"}


def test_timer_due_during_session_attaches(ha):
    pool = FakePool([_row(id="a")])
    sched = _sched(pool)
    run(_fire(sched))
    pool.rows.append(_row(id="b", name="B Timer"))
    run(_fire(sched))
    assert ha.scripts() == [START]  # no second melody
    assert sched._session_timer_ids == {"a", "b"}


def test_no_speaker_leaves_timer_undelivered(ha, monkeypatch):
    monkeypatch.setattr(timer_scheduler, "all_media_players", lambda: [])
    pool = FakePool([_row(id="a")])
    sched = _sched(pool)
    run(_fire(sched))
    assert ha.calls == []
    assert not sched.alarm_active()
    assert pool.rows[0]["status"] == "expired"  # announced on next contact


def test_offline_speaker_is_skipped(ha):
    ha.unavailable = {"media_player.kueche"}
    pool = FakePool([_row(id="a")])
    run(_fire(_sched(pool)))
    assert ha.calls == [(START, {
        "media_players": "media_player.buero",
        "max_seconds": timer_scheduler.MELODY_MAX_SECONDS,
    })]


def test_all_speakers_offline_leaves_timer_undelivered(ha):
    # QA BUG-10: HA accepts the script call even when every player is offline.
    ha.unavailable = {"media_player.buero", "media_player.kueche"}
    pool = FakePool([_row(id="a")])
    sched = _sched(pool)
    run(_fire(sched))
    assert ha.calls == []
    assert not sched.alarm_active()
    assert pool.rows[0]["status"] == "expired"
    res = run(sched.acknowledge_by_voice("esphome:Küche"))
    assert res["announcement"] == "Der 20 Minuten Timer ist abgelaufen."


def test_ha_unreachable_leaves_timer_undelivered(ha):
    ha.fail = True
    pool = FakePool([_row(id="a")])
    sched = _sched(pool)
    run(_fire(sched))
    assert not sched.alarm_active()
    assert pool.rows[0]["status"] == "expired"


def test_session_timeout_stops_everywhere_and_acks_timeout(ha, monkeypatch):
    monkeypatch.setattr(timer_scheduler, "MELODY_MAX_SECONDS", 0)
    pool = FakePool([_row(id="a"), _row(id="b")])
    sched = _sched(pool)

    async def go():
        await sched._fire_due()
        await sched._session_task

    run(go())
    assert ha.scripts() == [START, STOP]
    assert [(r["status"], r["acknowledged_by"]) for r in pool.rows] == [
        ("acknowledged", "timeout"), ("acknowledged", "timeout")]
    assert not sched.alarm_active()


def test_session_timeout_noop_after_voice_ack(ha, monkeypatch):
    monkeypatch.setattr(timer_scheduler, "MELODY_MAX_SECONDS", 0)
    pool = FakePool([_row(id="a")])
    sched = _sched(pool)

    async def go():
        await sched._fire_due()
        await sched.acknowledge_by_voice("esphome:Küche")
        await sched._session_task

    run(go())
    assert ha.scripts() == [START, STOP]  # no second stop from the timeout
    assert pool.rows[0]["acknowledged_by"] == "voice"


def test_stale_undelivered_timer_is_swept(ha):
    old = _now() - timedelta(seconds=timer_scheduler.ANNOUNCE_CUTOFF_SECONDS + 60)
    pool = FakePool([_row(id="a", status="expired", fired_at=old)])
    run(_fire(_sched(pool)))
    assert (pool.rows[0]["status"], pool.rows[0]["acknowledged_by"]) == ("acknowledged", "timeout")


def test_reconcile_on_start_fires_overdue(ha):
    pool = FakePool([_row(id="a", expires_at=_now() - timedelta(minutes=5))])
    sched = _sched(pool)
    run(sched._reconcile_on_start())
    sched._session_task.cancel()
    assert pool.rows[0]["status"] == "expired"


# ---------------------------------------------------------------------------
# Voice acknowledgement (GET /stream/timers/pending)
# ---------------------------------------------------------------------------
def test_pending_announcement_any_device_any_role():
    pool = FakePool([
        _expired(id="a", name="20 Minuten Timer", origin_channel="webapp",
                 expires_at=_now() - timedelta(seconds=9)),
        _expired(id="b", name="Kartoffel Timer", origin_channel="esphome:Büro",
                 owner_role="child", expires_at=_now() - timedelta(seconds=8)),
    ])
    text = run(pending_announcement(pool))
    assert text == "Der 20 Minuten Timer und Kartoffel Timer sind abgelaufen."
    assert all(r["acknowledged_by"] == "voice" for r in pool.rows)
    assert run(pending_announcement(pool)) is None  # claimed exactly once


def test_pending_announcement_skips_too_old():
    old = _now() - timedelta(seconds=timer_scheduler.ANNOUNCE_CUTOFF_SECONDS + 60)
    pool = FakePool([_row(id="a", status="expired", fired_at=old)])
    assert run(pending_announcement(pool)) is None


def test_voice_ack_stops_all_and_announces(ha):
    pool = FakePool([_row(id="a")])
    sched = _sched(pool)
    run(_fire(sched))
    res = run(sched.acknowledge_by_voice("esphome:Küche"))
    assert res == {"announcement": "Der 20 Minuten Timer ist abgelaufen.",
                   "alarm_acknowledged": True}
    assert ha.calls[-1] == (STOP, {"media_players": "media_player.buero,media_player.kueche"})
    assert not sched.alarm_active()


def test_two_devices_at_once_one_announcement(ha):
    pool = FakePool([_row(id="a")])
    sched = _sched(pool)
    run(_fire(sched))
    first = run(sched.acknowledge_by_voice("esphome:Küche"))
    second = run(sched.acknowledge_by_voice("esphome:Büro"))
    assert first["announcement"] and first["alarm_acknowledged"]
    # lost the race: no text, but still a pure acknowledgement
    assert second == {"announcement": None, "alarm_acknowledged": True}


def test_same_device_follow_up_turn_is_normal(ha):
    pool = FakePool([_row(id="a")])
    sched = _sched(pool)
    run(_fire(sched))
    run(sched.acknowledge_by_voice("esphome:Küche"))
    again = run(sched.acknowledge_by_voice("esphome:Küche"))
    assert again == {"announcement": None, "alarm_acknowledged": False}


def test_normal_turn_without_alarm_touches_no_speaker(ha):
    sched = _sched(FakePool([]))
    res = run(sched.acknowledge_by_voice("esphome:Küche"))
    assert res == {"announcement": None, "alarm_acknowledged": False}
    assert ha.calls == []


def test_undelivered_timer_announced_on_any_device(ha):
    pool = FakePool([_expired(id="a")])  # no session (nothing could ring)
    sched = _sched(pool)
    res = run(sched.acknowledge_by_voice("esphome:Büro"))
    assert res["announcement"] == "Der 20 Minuten Timer ist abgelaufen."
    assert ha.scripts() == [STOP]  # make sure nothing still loops


# ---------------------------------------------------------------------------
# WebApp acknowledgement (POST /stream/timers/acknowledge)
# ---------------------------------------------------------------------------
def test_webapp_ack_stops_melody_when_nothing_else_rings(ha):
    pool = FakePool([_row(id="a")])
    sched = _sched(pool)
    run(_fire(sched))
    assert run(sched.acknowledge_webapp("admin", ["a"])) == 1
    assert pool.rows[0]["acknowledged_by"] == "webapp"
    assert ha.scripts() == [START, STOP]
    assert not sched.alarm_active()


def test_webapp_ack_other_role_keeps_melody(ha):
    pool = FakePool([_row(id="a", owner_role="child"), _row(id="b", owner_role="admin")])
    sched = _sched(pool)
    run(_fire(sched))
    assert run(sched.acknowledge_webapp("child", ["a"])) == 1
    assert ha.scripts() == [START]  # admin alarm still rings
    assert sched.alarm_active()


def test_webapp_ack_is_role_scoped(ha):
    pool = FakePool([_expired(id="a", owner_role="admin")])
    sched = _sched(pool)
    assert run(sched.acknowledge_webapp("child", ["a"])) == 0
    assert pool.rows[0]["status"] == "expired"


def test_webapp_ack_idempotent_after_voice(ha):
    pool = FakePool([_row(id="a")])
    sched = _sched(pool)
    run(_fire(sched))
    run(sched.acknowledge_by_voice("esphome:Küche"))
    assert run(sched.acknowledge_webapp("admin", ["a"])) == 0
    assert pool.rows[0]["acknowledged_by"] == "voice"


def test_webapp_ack_of_catch_up_marks_webapp_and_leaves_speakers_alone(ha):
    # QA BUG-13: nothing rings — no media_stop on the speakers.
    pool = FakePool([_row(id="a", status="acknowledged", acknowledged_by="timeout",
                          fired_at=_now() - timedelta(minutes=3))])
    run(_sched(pool).acknowledge_webapp("admin", ["a"]))
    assert pool.rows[0]["acknowledged_by"] == "webapp"
    assert ha.calls == []


def test_webapp_ack_before_watcher_fired_prevents_ringing(ha):
    # QA BUG-12: the browser countdown ran a moment ahead of the watcher.
    pool = FakePool([_row(id="a", expires_at=_now() + timedelta(seconds=2))])
    sched = _sched(pool)
    assert run(sched.acknowledge_webapp("admin", ["a"])) == 1
    assert pool.rows[0]["fired_at"] is not None
    run(_fire(sched))
    assert ha.calls == []  # never rings


def test_webapp_ack_does_not_touch_far_future_timer(ha):
    pool = FakePool([_row(id="a", expires_at=_now() + timedelta(minutes=5))])
    assert run(_sched(pool).acknowledge_webapp("admin", ["a"])) == 0
    assert pool.rows[0]["status"] == "running"


# ---------------------------------------------------------------------------
# WebApp list: recently expired, not actively acknowledged
# ---------------------------------------------------------------------------
def test_list_recent_expired_excludes_actively_acknowledged():
    recent = _now() - timedelta(minutes=2)
    pool = FakePool([
        _row(id="ringing", status="expired", fired_at=recent),
        _row(id="timeout", status="acknowledged", acknowledged_by="timeout", fired_at=recent),
        _row(id="voice", status="acknowledged", acknowledged_by="voice", fired_at=recent),
        _row(id="webapp", status="acknowledged", acknowledged_by="webapp", fired_at=recent),
        _row(id="other-role", status="expired", fired_at=recent, owner_role="child"),
        _row(id="too-old", status="expired", fired_at=_now() - timedelta(minutes=20)),
    ])
    rows = run(timers.list_recent_expired(pool, "admin", 15 * 60))
    assert sorted(r["id"] for r in rows) == ["ringing", "timeout"]


# ---------------------------------------------------------------------------
# all_media_players — device-mapping.yaml (+ env override)
# ---------------------------------------------------------------------------
DEVICE_MAPPING_YAML = """
devices:
  "192.168.1.10":
    name: "Büro HA Voice PE"
    room: "Büro"
    media_player: "media_player.ha_voice_pe_buero_media_player"
  "192.168.1.11":
    name: "Küche HA Voice PE"
    room: "Küche"
    media_player: "media_player.ha_voice_pe_kueche_media_player"
  "192.168.1.12":
    name: "Bad (no speaker entry)"
    room: "Bad"
"""


@pytest.fixture
def mapping_file(tmp_path, monkeypatch):
    p = tmp_path / "device-mapping.yaml"
    p.write_text(DEVICE_MAPPING_YAML)
    monkeypatch.setattr(timer_scheduler, "DEVICE_MAPPING_PATH", str(p))
    return p


def test_all_media_players_from_mapping(mapping_file, monkeypatch):
    monkeypatch.delenv("TIMER_MEDIA_PLAYER_MAP", raising=False)
    assert timer_scheduler.all_media_players() == [
        "media_player.ha_voice_pe_buero_media_player",
        "media_player.ha_voice_pe_kueche_media_player",
    ]


def test_all_media_players_adds_env_override_deduplicated(mapping_file, monkeypatch):
    monkeypatch.setenv(
        "TIMER_MEDIA_PLAYER_MAP",
        "esphome:Bad=media_player.bad,esphome:Büro=media_player.ha_voice_pe_buero_media_player",
    )
    assert timer_scheduler.all_media_players() == [
        "media_player.ha_voice_pe_buero_media_player",
        "media_player.ha_voice_pe_kueche_media_player",
        "media_player.bad",
    ]


def test_all_media_players_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(timer_scheduler, "DEVICE_MAPPING_PATH", str(tmp_path / "nope.yaml"))
    monkeypatch.delenv("TIMER_MEDIA_PLAYER_MAP", raising=False)
    assert timer_scheduler.all_media_players() == []
