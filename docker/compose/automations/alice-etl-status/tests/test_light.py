"""Traffic light and highlighting rules (AK-30, AK-37) and run percent (AK-36). No database needed."""
from datetime import datetime, timedelta, timezone

from app.main import needs_attention, run_percent, traffic_light

NOW = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)


def res(state="complete", hours=2, reported=0, repaired=0, repair_failed=0):
    return {"state": state, "finished_at": (NOW - timedelta(hours=hours)).isoformat(),
            "summary": {"levels": {"1": {"reported": reported, "repaired": repaired, "repair_failed": repair_failed},
                                   "3": {"reported": 0}}}}


def test_green():
    assert traffic_light(res(), 0, NOW) == "green"
    assert traffic_light(res(repaired=4), 0, NOW) == "green"


def test_yellow():
    assert traffic_light(res(), 1, NOW) == "yellow"
    assert traffic_light(res(reported=2), 0, NOW) == "yellow"
    assert traffic_light(res(repair_failed=1), 0, NOW) == "yellow"


def test_red():
    assert traffic_light(None, 0, NOW) == "red"
    assert traffic_light(res(state="incomplete"), 0, NOW) == "red"
    assert traffic_light(res(hours=37), 0, NOW) == "red"
    assert traffic_light(res(state="incomplete"), 3, NOW) == "red"


def test_attention():
    assert needs_attention(res(hours=2), NOW) is False
    assert needs_attention(res(hours=35.9), NOW) is False
    assert needs_attention(res(hours=36.1), NOW) is True
    assert needs_attention(res(state="incomplete"), NOW) is True


def test_percent():
    assert run_percent({"in_run": 100, "finished": 63}) == 63
    assert run_percent({"in_run": 0, "finished": 0}) == 100
    assert run_percent(None) is None
