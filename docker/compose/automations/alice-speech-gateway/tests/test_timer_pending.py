"""PROJ-85 Refinement 2026-10-15 — parsing of the /stream/timers/pending reply
(announcement + alarm_acknowledged flag)."""
from __future__ import annotations

import httpx
import pytest

from app.wyoming_transport import GatewayWyomingHandler


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _client_returning(resp=None, exc=None, seen=None):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            if seen is not None:
                seen.append(params)
            if exc:
                raise exc
            return resp

    return _Client


async def _call(monkeypatch, client_cls):
    monkeypatch.setattr(httpx, "AsyncClient", client_cls)
    handler = GatewayWyomingHandler.__new__(GatewayWyomingHandler)
    return await handler._announce_expired_timers("Küche", "tok")


async def test_announcement_and_flag(monkeypatch):
    seen = []
    resp = _Resp(200, {"announcement": "Der 20 Minuten Timer ist abgelaufen.",
                       "alarm_acknowledged": True})
    result = await _call(monkeypatch, _client_returning(resp, seen=seen))
    assert result == ("Der 20 Minuten Timer ist abgelaufen.", True)
    assert seen == [{"channel": "esphome:Küche"}]


async def test_lost_race_is_pure_ack_without_text(monkeypatch):
    resp = _Resp(200, {"announcement": None, "alarm_acknowledged": True})
    assert await _call(monkeypatch, _client_returning(resp)) == (None, True)


async def test_old_server_reply_without_flag(monkeypatch):
    resp = _Resp(200, {"announcement": None})
    assert await _call(monkeypatch, _client_returning(resp)) == (None, False)


@pytest.mark.parametrize("resp,exc", [
    (_Resp(403, {}), None),
    (None, httpx.ConnectError("down")),
])
async def test_errors_mean_normal_turn(monkeypatch, resp, exc):
    assert await _call(monkeypatch, _client_returning(resp, exc)) == (None, False)
