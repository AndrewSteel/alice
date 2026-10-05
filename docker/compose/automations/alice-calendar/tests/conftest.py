"""
In-memory fakes for Google (PROJ-86 + Calendar API), the selection table and
Redis, so the agent logic runs end-to-end without network or database.
"""
import itertools
from datetime import datetime

import pytest

from app import agent, db, google, tickets
from app import timeutil as tu
from app.auth import Caller

TZ = tu.zone("Europe/Berlin")
USER = "11111111-1111-1111-1111-111111111111"
CONN_A = "aaaaaaaa-0000-0000-0000-000000000001"
CONN_B = "bbbbbbbb-0000-0000-0000-000000000002"


class FakeGoogle:
    def __init__(self):
        self.connections = []          # PROJ-86 connection dicts
        self.calendars = {}            # conn_id -> [calendarList entries]
        self.events = {}               # (conn_id, cal_id) -> [event dicts]
        self.token_errors = {}         # conn_id -> exception to raise (or list for sequence)
        self.calendar_errors = {}      # (conn_id, cal_id) -> exception for list_events
        self.calls = []
        self._ids = itertools.count(1)
        self.token_to_conn = {}

    # helpers -------------------------------------------------------------
    def add_connection(self, conn_id, account, scopes=None, status="active"):
        self.connections.append({
            "id": conn_id, "google_account": account, "status": status,
            "scopes": scopes if scopes is not None else ["openid", "email", *google.CALENDAR_SCOPES],
        })
        self.calendars.setdefault(conn_id, [])

    def add_calendar(self, conn_id, cal_id, name, role="owner", primary=False):
        self.calendars[conn_id].append({"id": cal_id, "summary": name, "accessRole": role,
                                        "primary": primary, "backgroundColor": "#123456"})
        self.events.setdefault((conn_id, cal_id), [])

    def add_event(self, conn_id, cal_id, summary, start, end, all_day=False, **extra):
        eid = extra.pop("id", None) or f"ev{next(self._ids)}"
        if all_day:
            ev = {"start": {"date": start}, "end": {"date": end}}
        else:
            ev = {"start": {"dateTime": start}, "end": {"dateTime": end}}
        ev.update({"id": eid, "summary": summary, "etag": f'"{eid}-1"', "status": "confirmed", **extra})
        self.events[(conn_id, cal_id)].append(ev)
        return ev

    def _conn_of(self, token):
        return self.token_to_conn[token]

    # PROJ-86 ---------------------------------------------------------------
    async def list_connections(self, client, user_token):
        return list(self.connections)

    async def get_access_token(self, client, user_token, connection_id):
        self.calls.append(("token", connection_id))
        err = self.token_errors.get(connection_id)
        if err:
            raise err
        tok = f"tok-{connection_id}"
        self.token_to_conn[tok] = connection_id
        return tok

    # Calendar API ----------------------------------------------------------
    async def list_calendars(self, client, token):
        return list(self.calendars[self._conn_of(token)])

    async def list_events(self, client, token, cal_id, time_min, time_max, tz_name, max_results=250):
        conn = self._conn_of(token)
        err = self.calendar_errors.get((conn, cal_id))
        if err:
            raise err
        if (conn, cal_id) not in self.events:
            raise google.NotFound(cal_id)
        lo, hi = datetime.fromisoformat(time_min), datetime.fromisoformat(time_max)
        out = []
        for ev in self.events[(conn, cal_id)]:
            t = tu.parse_event_times(ev, TZ)
            if t.end > lo and t.start < hi:
                out.append(dict(ev))
        out.sort(key=lambda e: tu.parse_event_times(e, TZ).start)
        return out[:max_results]

    def _find(self, conn, cal_id, event_id):
        for ev in self.events.get((conn, cal_id), []):
            if ev["id"] == event_id:
                return ev
        raise google.NotFound(event_id)

    async def get_event(self, client, token, cal_id, event_id):
        return dict(self._find(self._conn_of(token), cal_id, event_id))

    async def insert_event(self, client, token, cal_id, body):
        conn = self._conn_of(token)
        eid = f"new{next(self._ids)}"
        ev = {**body, "id": eid, "etag": f'"{eid}-1"', "status": "confirmed"}
        self.events[(conn, cal_id)].append(ev)
        self.calls.append(("insert", conn, cal_id, body))
        return dict(ev)

    async def patch_event(self, client, token, cal_id, event_id, body):
        ev = self._find(self._conn_of(token), cal_id, event_id)
        ev.update(body)
        ev["etag"] = ev["etag"].rstrip('"') + 'x"'
        self.calls.append(("patch", cal_id, event_id, body))
        return dict(ev)

    async def move_event(self, client, token, cal_id, event_id, destination):
        conn = self._conn_of(token)
        ev = self._find(conn, cal_id, event_id)
        self.events[(conn, cal_id)].remove(ev)
        self.events[(conn, destination)].append(ev)
        self.calls.append(("move", cal_id, event_id, destination))
        return dict(ev)

    async def delete_event(self, client, token, cal_id, event_id):
        conn = self._conn_of(token)
        ev = self._find(conn, cal_id, event_id)
        self.events[(conn, cal_id)].remove(ev)
        self.calls.append(("delete", cal_id, event_id))


class FakeDB:
    def __init__(self):
        self.rows = []  # dicts: connection_id, calendar_id, is_active, is_default

    def select(self, conn, cal, default=False):
        self.rows.append({"connection_id": conn, "calendar_id": cal, "is_active": True, "is_default": default})

    async def list_selections(self, user_id):
        return [dict(r) for r in self.rows]

    async def delete_selections(self, user_id, connection_id, calendar_ids):
        self.rows = [r for r in self.rows
                     if not (r["connection_id"] == connection_id and r["calendar_id"] in calendar_ids)]

    async def clear_default(self, user_id, connection_id, calendar_id):
        for r in self.rows:
            if r["connection_id"] == connection_id and r["calendar_id"] == calendar_id:
                r["is_default"] = False

    async def set_selection(self, user_id, connection_id, calendar_id, is_active, is_default, writable):
        self.last_set = (connection_id, calendar_id, is_active, is_default, writable)


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


@pytest.fixture
def fg(monkeypatch):
    fake = FakeGoogle()
    for name in ("list_connections", "get_access_token", "list_calendars", "list_events",
                 "get_event", "insert_event", "patch_event", "move_event", "delete_event"):
        monkeypatch.setattr(google, name, getattr(fake, name))
    return fake


@pytest.fixture
def fdb(monkeypatch):
    fake = FakeDB()
    for name in ("list_selections", "delete_selections", "clear_default", "set_selection"):
        monkeypatch.setattr(db, name, getattr(fake, name))
    return fake


@pytest.fixture
def fredis():
    fake = FakeRedis()
    tickets.set_client(fake)
    yield fake
    tickets.set_client(None)


@pytest.fixture
def make_ctx():
    def _make(now=datetime(2026, 10, 7, 9, 30, tzinfo=TZ), channel="chat", session="s1", turn=1,
              user=USER):
        return agent.Ctx(
            caller=Caller(user_id=user, role="user", token="jwt", issuer=None),
            client=None, tz_name="Europe/Berlin", tz=TZ, now=now,
            channel=channel, session_id=session, turn=turn,
        )
    return _make


@pytest.fixture
def basic(fg, fdb):
    """One account, two active calendars (default 'Privat' + 'Familie'), one read-only holiday cal."""
    fg.add_connection(CONN_A, "me@gmail.com")
    fg.add_calendar(CONN_A, "primary-a", "Privat", primary=True)
    fg.add_calendar(CONN_A, "family", "Familie")
    fg.add_calendar(CONN_A, "holidays", "Feiertage in Deutschland", role="reader")
    fdb.select(CONN_A, "primary-a", default=True)
    fdb.select(CONN_A, "family")
    fdb.select(CONN_A, "holidays")
    return fg
