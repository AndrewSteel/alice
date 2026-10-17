"""
PROJ-85 — Timer-Wächter (background expiry watcher).

A single asyncio task started from the FastAPI lifespan. It sleeps until the
next running timer is due, fires it, and repeats. `wake()` is called by the
timer handler whenever a timer is created / changed / deleted so the sleep is
recomputed.

Delivery (Refinement 2026-10-15 — the alarm belongs to the house, not to a
device or a role):
  * Voice PE  — every expiry starts ONE house-wide alarm session: Alice calls
    Home Assistant over REST to loop the melody on ALL Voice-PE media_players
    from device-mapping.yaml, regardless of where (voice / WebApp) or by which
    role the timer was set. Timers coming due while a session rings attach to
    it (no second melody). Addressing any Voice PE stops the melody everywhere
    (GET /stream/timers/pending, called by alice-speech-gateway at the start of
    every turn); closing the WebApp toast does too, unless another role's alarm
    is still unacknowledged. After the max time the session acknowledges its
    timers itself ('timeout').
  * WebApp    — no server push. The browser counts down to `expires_at` and
    shows the toast itself; a returning tab reads expired-but-not-actively-
    acknowledged rows for its catch-up message (PROJ-104 covers real push).

Concurrency (spec): the transition to `expired` is a conditional UPDATE that
only touches a row still `running`, so the restart reconcile and the steady
loop never fire the same timer twice. The announcement claim is a conditional
UPDATE on `expired` too, so of two devices addressed at once exactly one gets
the announcement.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import yaml

from . import timers as _timers

logger = logging.getLogger("alice-chat-stream.timer_scheduler")

LOCAL_TZ = ZoneInfo("Europe/Berlin")

HA_URL = os.environ.get("HA_URL", "http://homeassistant:8123").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

# Collect timers due within this window into one alarm session (spec default
# 3 s, global since Refinement 2026-10-15).
COLLECT_WINDOW_SECONDS = float(os.environ.get("TIMER_COLLECT_WINDOW_SECONDS", "3"))
# Self-stop for an un-acknowledged alarm session (spec default 2 min).
MELODY_MAX_SECONDS = int(os.environ.get("TIMER_MELODY_MAX_SECONDS", "120"))
# An expired timer that could not be delivered (no speaker reachable) is still
# announced on the next contact of any Voice PE within max time + this buffer
# (spec "innerhalb Maximalzeit + Puffer"); older ones are swept as 'timeout'.
ANNOUNCE_GRACE_SECONDS = 300
ANNOUNCE_CUTOFF_SECONDS = MELODY_MAX_SECONDS + ANNOUNCE_GRACE_SECONDS
# A device addressed this shortly after another device took the announcement
# counts as a pure acknowledgement too (two people, two devices, same moment).
VOICE_ACK_GRACE_SECONDS = 5.0
# Idle cap so a far-future timer still gets a periodic sanity check.
MAX_SLEEP_SECONDS = 3600

# HA scripts that own the melody playback (homeassistant/alice_timer_melody.yaml).
# Alice only signals start/stop.
HA_MELODY_START_SCRIPT = os.environ.get("TIMER_MELODY_START_SCRIPT", "script.alice_timer_melody_start")
HA_MELODY_STOP_SCRIPT = os.environ.get("TIMER_MELODY_STOP_SCRIPT", "script.alice_timer_melody_stop")

# alice-speech-gateway's device-mapping.yaml, mounted read-only into this
# container too (same config volume) — the source of truth for which Voice PE
# exists and which media_player it has (PROJ-40/42). A new device takes part
# in the alarm by getting a media_player entry there; no code change.
DEVICE_MAPPING_PATH = os.environ.get(
    "DEVICE_MAPPING_PATH", "/config/device-mapping.yaml"
)


def _load_mapping_media_players() -> list[str]:
    """Every media_player entity listed in device-mapping.yaml."""
    try:
        with open(DEVICE_MAPPING_PATH) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return []
    except yaml.YAMLError as exc:
        logger.error("device-mapping.yaml is invalid: %s", exc)
        return []

    players: list[str] = []
    for entry in (data.get("devices") or {}).values():
        if not isinstance(entry, dict):
            continue
        media_player = str(entry.get("media_player") or "").strip()
        if media_player:
            players.append(media_player)
    return players


def all_media_players() -> list[str]:
    """All Voice-PE speakers taking part in the alarm, deduplicated.

    device-mapping.yaml plus the explicit TIMER_MEDIA_PLAYER_MAP override
    ("esphome:<Raum>=media_player.<entity>,…" — only the values matter now).
    """
    players = _load_mapping_media_players()
    for pair in os.environ.get("TIMER_MEDIA_PLAYER_MAP", "").split(","):
        if "=" in pair:
            players.append(pair.split("=", 1)[1].strip())
    return list(dict.fromkeys(p for p in players if p))


class TimerScheduler:
    def __init__(self, pool_getter):
        self._pool_getter = pool_getter
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._stopped = False
        # House-wide alarm session (in memory — after a restart the HA timeout
        # automation is the safety net for a melody that was still looping).
        self._session_id = 0
        self._session_active = False
        self._session_timer_ids: set[str] = set()
        self._session_task: asyncio.Task | None = None
        self._last_voice_ack = 0.0
        self._last_voice_ack_channel: str | None = None

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="timer-scheduler")

    async def stop(self) -> None:
        self._stopped = True
        self._wake.set()
        for task in (self._task, self._session_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._session_task = None

    def wake(self) -> None:
        """Ask the loop to recompute its sleep (timer added / changed / deleted)."""
        self._wake.set()

    # -- main loop ---------------------------------------------------------
    async def _run(self) -> None:
        try:
            await self._reconcile_on_start()
        except Exception as exc:  # never let startup reconcile kill the loop
            logger.error("Timer reconcile on start failed: %s", exc)

        while not self._stopped:
            try:
                sleep_for = await self._seconds_to_next()
            except Exception as exc:
                logger.error("Timer scheduler poll failed: %s", exc)
                sleep_for = 30.0

            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=sleep_for)
                # woken early by wake() — loop again, recompute
                continue
            except asyncio.TimeoutError:
                pass

            if self._stopped:
                break
            try:
                await self._fire_due()
            except Exception as exc:
                logger.error("Timer fire pass failed: %s", exc)

    # -- helpers ---------------------------------------------------------
    def _pool(self):
        return self._pool_getter()

    async def _seconds_to_next(self) -> float:
        row = await self._pool().fetchrow(
            "SELECT MIN(expires_at) AS next FROM alice.timers WHERE status = 'running'"
        )
        if not row or row["next"] is None:
            return MAX_SLEEP_SECONDS
        delta = (row["next"] - datetime.now(LOCAL_TZ)).total_seconds()
        return max(0.0, min(delta, MAX_SLEEP_SECONDS))

    async def _reconcile_on_start(self) -> None:
        """Fire everything that came due while the service was down.

        The conditional-UPDATE claim in _fire_due makes this idempotent with
        the steady loop — an overdue timer is only ever transitioned once.
        """
        rows = await self._pool().fetch(
            "SELECT id FROM alice.timers "
            "WHERE status = 'running' AND expires_at <= NOW()"
        )
        if rows:
            logger.info("Timer reconcile: %d overdue timer(s) on start", len(rows))
        await self._fire_due()

    async def _fire_due(self) -> None:
        """Claim and deliver every running timer whose expiry has passed.

        The claim is a conditional UPDATE (`status = 'running'` guard) so a
        concurrent delete / change / a second pass cannot double-fire. The
        collect window pulls in timers coming due within the next few seconds
        so near-simultaneous timers share one alarm session (spec
        "Sammel-Fenster", global since Refinement 2026-10-15).
        """
        # Undelivered leftovers past the announcement cutoff end silently.
        await self._pool().execute(
            "UPDATE alice.timers SET status = 'acknowledged', "
            "acknowledged_by = 'timeout', updated_at = NOW() "
            "WHERE status = 'expired' "
            "AND fired_at < NOW() - make_interval(secs => $1)",
            ANNOUNCE_CUTOFF_SECONDS,
        )
        claimed = await self._pool().fetch(
            "UPDATE alice.timers SET status = 'expired', fired_at = NOW() "
            "WHERE status = 'running' "
            "AND expires_at <= NOW() + make_interval(secs => $1) "
            "RETURNING id, name, expires_at, origin_channel, owner_role",
            COLLECT_WINDOW_SECONDS,
        )
        if not claimed:
            return
        timers = [dict(r) for r in claimed]
        logger.info(
            "Timer(s) expired: %s",
            [(t["name"], t["origin_channel"], t["owner_role"]) for t in timers],
        )
        try:
            await self._deliver(timers)
        except Exception as exc:
            logger.error("Timer alarm delivery failed: %s", exc)

    async def _deliver(self, timers: list[dict]) -> None:
        """Ring all Voice PE for `timers`, or attach them to the running session.

        When nothing can be delivered (no HA token, no speaker configured, HA
        unreachable) the rows stay 'expired, not delivered' and are announced
        by the next Voice PE that is addressed within the cutoff.
        """
        ids = {str(t["id"]) for t in timers}
        if self._session_active:
            # Spec: a timer coming due while the melody rings attaches to the
            # session — no second melody.
            self._session_timer_ids |= ids
            return

        configured = all_media_players()
        if not HA_TOKEN or not configured:
            logger.warning(
                "Timer alarm not delivered (HA_TOKEN set: %s, media_players: %d) — "
                "will announce on next Voice-PE contact", bool(HA_TOKEN), len(configured),
            )
            return

        headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Skip offline speakers; with none reachable the alarm counts
                # as not delivered (HA would accept the script call anyway).
                players = [p for p in configured if await self._player_available(client, p, headers)]
                if not players:
                    logger.warning(
                        "Timer alarm not delivered — no media_player reachable of %s; "
                        "will announce on next Voice-PE contact", configured,
                    )
                    return
                resp = await client.post(
                    f"{HA_URL}/api/services/script/turn_on",
                    json={
                        "entity_id": HA_MELODY_START_SCRIPT,
                        "variables": {
                            "media_players": ",".join(players),
                            "max_seconds": MELODY_MAX_SECONDS,
                        },
                    },
                    headers=headers,
                )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Melody start call failed — timer(s) stay undelivered: %s", exc)
            return

        logger.info("Timer alarm session started on %s", players)
        self._session_id += 1
        self._session_active = True
        self._session_timer_ids = ids
        self._session_task = asyncio.create_task(self._end_session_after_max(self._session_id))

    @staticmethod
    async def _player_available(client, entity_id: str, headers: dict) -> bool:
        try:
            resp = await client.get(f"{HA_URL}/api/states/{entity_id}", headers=headers)
        except Exception as exc:
            logger.warning("media_player state check failed for %s: %s", entity_id, exc)
            return False
        if resp.status_code != 200:
            return False
        return (resp.json() or {}).get("state") not in ("unavailable", "unknown", None)

    async def _end_session_after_max(self, session_id: int) -> None:
        """Nobody reacted within the max time: stop everywhere and acknowledge
        the session's timers as 'timeout'."""
        await asyncio.sleep(MELODY_MAX_SECONDS)
        if session_id != self._session_id or not self._session_active:
            return  # already ended by voice / WebApp, or a newer session
        ids = list(self._session_timer_ids)
        await self.stop_melody()
        try:
            await self._pool().execute(
                "UPDATE alice.timers SET status = 'acknowledged', "
                "acknowledged_by = 'timeout', updated_at = NOW() "
                "WHERE id = ANY($1::uuid[]) AND status = 'expired'",
                ids,
            )
        except Exception as exc:
            logger.warning("Auto-acknowledge failed: %s", exc)

    # -- alarm session control -------------------------------------------
    def alarm_active(self) -> bool:
        return self._session_active

    def note_voice_ack(self, channel: str | None) -> None:
        self._last_voice_ack = time.monotonic()
        self._last_voice_ack_channel = channel

    def recent_voice_ack_elsewhere(self, channel: str | None) -> bool:
        """Another device took the announcement a moment ago. The device that
        took it is excluded — its follow-up turn is a real command."""
        return (
            channel != self._last_voice_ack_channel
            and time.monotonic() - self._last_voice_ack <= VOICE_ACK_GRACE_SECONDS
        )

    async def stop_melody(self) -> None:
        """End the alarm session and stop the melody on all speakers."""
        self._session_active = False
        self._session_timer_ids = set()
        if not HA_TOKEN:
            return
        headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{HA_URL}/api/services/script/turn_on",
                    json={
                        "entity_id": HA_MELODY_STOP_SCRIPT,
                        "variables": {"media_players": ",".join(all_media_players())},
                    },
                    headers=headers,
                )
        except Exception as exc:
            logger.warning("Melody stop call failed: %s", exc)

    async def stop_if_nothing_ringing(self) -> None:
        """Stop the melody unless another expired, unacknowledged timer is
        still within the alarm — so closing one role's toast (or deleting one
        timer) cannot silence another role's alarm nobody has noticed yet."""
        if not self._session_active:
            return  # nothing rings — leave the speakers alone
        row = await self._pool().fetchrow(
            "SELECT 1 FROM alice.timers WHERE status = 'expired' "
            "AND fired_at >= NOW() - make_interval(secs => $1) LIMIT 1",
            ANNOUNCE_CUTOFF_SECONDS,
        )
        if row is None:
            await self.stop_melody()

    # -- acknowledgement entry points (the /stream/timers endpoints) -------
    async def acknowledge_by_voice(self, channel: str | None) -> dict:
        """A turn started on Voice PE `channel`: stop a ringing alarm on all
        speakers, claim every expired timer for this device's announcement.
        `alarm_acknowledged` marks the utterance as a pure acknowledgement —
        also for the device that lost the race against another device
        addressed at the same moment (it gets no text)."""
        ringing = self._session_active
        if ringing:
            await self.stop_melody()
        text = await pending_announcement(self._pool())
        if text:
            self.note_voice_ack(channel)
            logger.info("Timer alarm acknowledged by voice on %s", channel)
            if not ringing:
                # Undelivered alarm, or a melody still looping from before a
                # restart (no in-memory session) — make sure it is silent.
                await self.stop_melody()
        return {
            "announcement": text,
            "alarm_acknowledged": (
                bool(text) or ringing or self.recent_voice_ack_elsewhere(channel)
            ),
        }

    async def acknowledge_webapp(self, role: str, timer_ids: list[str]) -> int:
        """The WebApp toast was closed: acknowledge in the role scope, then
        stop the melody unless another alarm still rings."""
        count = await _timers.acknowledge_webapp(self._pool(), role, timer_ids)
        await self.stop_if_nothing_ringing()
        return count


# ---------------------------------------------------------------------------
# Voice-PE announcement claim (called by /stream/timers/pending, which
# alice-speech-gateway polls at the start of every turn on any device).
# ---------------------------------------------------------------------------
def announcement_text(names: list[str]) -> str:
    if len(names) == 1:
        return f"Der {names[0]} ist abgelaufen."
    joined = " und ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 2 else " und ".join(names)
    return f"Der {joined} sind abgelaufen."


async def pending_announcement(pool) -> str | None:
    """German sentence naming every expired, unacknowledged timer — of any
    device, any role (the acknowledgement is house-wide and role-independent)
    — and mark them acknowledged ('voice'). None when there is nothing to say.

    A single conditional UPDATE is the atomic claim: of two devices addressed
    at the same moment, the second finds no 'expired' row left.
    """
    rows = await pool.fetch(
        "UPDATE alice.timers SET status = 'acknowledged', "
        "acknowledged_by = 'voice', updated_at = NOW() "
        "WHERE status = 'expired' "
        "AND fired_at >= NOW() - make_interval(secs => $1) "
        "RETURNING name, expires_at",
        ANNOUNCE_CUTOFF_SECONDS,
    )
    if not rows:
        return None
    names = [r["name"] for r in sorted(rows, key=lambda r: r["expires_at"])]
    return announcement_text(names)
