"""PROJ-85 — timer scheduler: due-claim idempotency, channel grouping,
pending announcement wording."""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import timer_scheduler
from app.timer_scheduler import TimerScheduler, pending_announcement

TZ = ZoneInfo("Europe/Berlin")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


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

    async def fetch(self, sql, *a):
        return await self.store.fetch(sql, *a)

    async def execute(self, sql, *a):
        return await self.store.execute(sql, *a)


class FakePool:
    def __init__(self, rows):
        self.rows = rows
        self.melody_calls = []

    def acquire(self):
        pool = self

        class _Acq:
            async def __aenter__(self_):
                return FakeConn(pool)

            async def __aexit__(self_, *a):
                return False

        return _Acq()

    def _n(self, sql):
        return " ".join(sql.split())

    async def fetchrow(self, sql, *a):
        s = self._n(sql)
        if "MIN(expires_at)" in s:
            running = [r["expires_at"] for r in self.rows if r["status"] == "running"]
            return {"next": min(running) if running else None}
        return None

    async def fetch(self, sql, *a):
        s = self._n(sql)
        if s.startswith("UPDATE alice.timers SET status = 'expired'"):
            window = a[0] if a else 0
            cutoff = datetime.now(TZ) + timedelta(seconds=window)
            claimed = []
            for r in self.rows:
                if r["status"] == "running" and r["expires_at"] <= cutoff:
                    r["status"] = "expired"
                    claimed.append({
                        "id": r["id"], "name": r["name"],
                        "expires_at": r["expires_at"],
                        "origin_channel": r["origin_channel"],
                        "owner_role": r["owner_role"],
                    })
            return claimed
        if "SELECT id FROM alice.timers" in s and "expires_at <= NOW()" in s:
            return [
                {"id": r["id"]} for r in self.rows
                if r["status"] == "running" and r["expires_at"] <= datetime.now(TZ)
            ]
        if "SELECT id, name FROM alice.timers" in s and "status = 'expired'" in s:
            ch = a[0]
            return [
                {"id": r["id"], "name": r["name"]}
                for r in self.rows
                if r["origin_channel"] == ch and r["status"] == "expired"
            ]
        return []

    async def execute(self, sql, *a):
        s = self._n(sql)
        if "SET status = 'acknowledged'" in s:
            ids = set(str(x) for x in a[0])
            for r in self.rows:
                if str(r["id"]) in ids and r["status"] == "expired":
                    r["status"] = "acknowledged"
        return "OK"


def _row(**kw):
    base = {
        "id": "r1", "name": "20 Minuten Timer", "status": "running",
        "expires_at": datetime.now(TZ) - timedelta(seconds=1),
        "origin_channel": "webapp", "owner_role": "admin",
    }
    base.update(kw)
    return base


def test_fire_due_claims_once(monkeypatch):
    pool = FakePool([_row(id="r1", origin_channel="webapp")])
    sched = TimerScheduler(lambda: pool)
    run(sched._fire_due())
    assert pool.rows[0]["status"] == "expired"
    # a second pass claims nothing new
    run(sched._fire_due())
    assert pool.rows[0]["status"] == "expired"


def test_fire_due_voice_calls_ha(monkeypatch):
    calls = []

    async def fake_deliver(self, channel, timers):
        calls.append((channel, [t["name"] for t in timers]))

    monkeypatch.setattr(TimerScheduler, "_deliver_voice", fake_deliver)
    pool = FakePool([
        _row(id="a", name="A Timer", origin_channel="esphome:Küche"),
        _row(id="b", name="B Timer", origin_channel="esphome:Küche"),
        _row(id="c", name="C Timer", origin_channel="webapp"),
    ])
    sched = TimerScheduler(lambda: pool)
    run(sched._fire_due())
    assert calls == [("esphome:Küche", ["A Timer", "B Timer"])]


def test_pending_announcement_single():
    pool = FakePool([_row(id="a", name="20 Minuten Timer",
                          origin_channel="esphome:Küche", status="expired")])
    text = run(pending_announcement(pool, "esphome:Küche"))
    assert text == "Der 20 Minuten Timer ist abgelaufen."
    # marked acknowledged -> nothing to announce next time
    assert run(pending_announcement(pool, "esphome:Küche")) is None


def test_pending_announcement_multiple():
    pool = FakePool([
        _row(id="a", name="20 Minuten Timer", origin_channel="esphome:Küche", status="expired"),
        _row(id="b", name="Kartoffel Timer", origin_channel="esphome:Küche", status="expired"),
    ])
    text = run(pending_announcement(pool, "esphome:Küche"))
    assert "20 Minuten Timer" in text and "Kartoffel Timer" in text
    assert "sind abgelaufen" in text


def test_reconcile_on_start_fires_overdue(monkeypatch):
    monkeypatch.setattr(
        TimerScheduler, "_deliver_voice",
        lambda self, c, t: asyncio.sleep(0),
    )
    pool = FakePool([_row(id="a", origin_channel="webapp",
                          expires_at=datetime.now(TZ) - timedelta(minutes=5))])
    sched = TimerScheduler(lambda: pool)
    run(sched._reconcile_on_start())
    assert pool.rows[0]["status"] == "expired"
