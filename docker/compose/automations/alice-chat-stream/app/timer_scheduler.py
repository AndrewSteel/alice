"""
PROJ-85 — Timer-Wächter (background expiry watcher).

A single asyncio task started from the FastAPI lifespan. It sleeps until the
next running timer is due, fires it, and repeats. `wake()` is called by the
timer handler whenever a timer is created / changed / deleted so the sleep is
recomputed.

Delivery per channel:
  * Voice PE  — Alice calls Home Assistant over REST to play a melody on the
    media_player of the setting device, then a companion HA automation stops
    it when the satellite is addressed or a max time elapses.
    >>> HARDWARE-VERIFY (spec open point): whether the Voice PE media_player
        is usable while the "Hey Jarvis" Wyoming session is idle, and how
        reliably the HA automation sees "satellite is being addressed". The
        REST call + automation trigger below are the intended path; confirm at
        the device and adjust `_deliver_voice` / homeassistant/timer_melody.yaml
        if the fallback (fixed short tone over the TTS channel) is needed.
  * WebApp    — no server push. The browser counts down to the `expires_at`
    it got at creation and shows the toast itself; the watcher only marks the
    row so a returning tab can show a catch-up message (PROJ-104 covers real
    background push).

Concurrency (spec): the transition to `expired` is a conditional UPDATE that
only touches a row still `running`, so the restart reconcile and the steady
loop never fire the same timer twice.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger("alice-chat-stream.timer_scheduler")

LOCAL_TZ = ZoneInfo("Europe/Berlin")

HA_URL = os.environ.get("HA_URL", "http://homeassistant:8123").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

# Collect timers of the same device due within this window into one melody +
# one announcement (spec default 3 s).
COLLECT_WINDOW_SECONDS = float(os.environ.get("TIMER_COLLECT_WINDOW_SECONDS", "3"))
# Self-stop for an un-acknowledged Voice-PE melody (spec default 2 min).
MELODY_MAX_SECONDS = int(os.environ.get("TIMER_MELODY_MAX_SECONDS", "120"))
# Idle cap so a far-future timer still gets a periodic sanity check.
MAX_SLEEP_SECONDS = 3600

# HA automation entity that owns the melody playback (see
# homeassistant/timer_melody.yaml). Alice only signals start/stop.
HA_MELODY_START_SCRIPT = os.environ.get("TIMER_MELODY_START_SCRIPT", "script.alice_timer_melody_start")
HA_MELODY_STOP_SCRIPT = os.environ.get("TIMER_MELODY_STOP_SCRIPT", "script.alice_timer_melody_stop")


class TimerScheduler:
    def __init__(self, pool_getter):
        self._pool_getter = pool_getter
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._stopped = False

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="timer-scheduler")

    async def stop(self) -> None:
        self._stopped = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

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
        so several near-simultaneous timers of one device fire together (spec
        "Sammel-Fenster", one melody, one announcement).
        """
        claimed = await self._pool().fetch(
            "UPDATE alice.timers SET status = 'expired', fired_at = NOW() "
            "WHERE status = 'running' "
            "AND expires_at <= NOW() + make_interval(secs => $1) "
            "RETURNING id, name, expires_at, origin_channel, owner_role",
            COLLECT_WINDOW_SECONDS,
        )
        if not claimed:
            return

        # Group by origin channel for the 3 s collect window (Voice PE only —
        # WebApp rows just get marked).
        by_channel: dict[str, list[dict]] = {}
        for r in claimed:
            by_channel.setdefault(r["origin_channel"], []).append(dict(r))

        for channel, timers in by_channel.items():
            if channel == "webapp":
                # Nothing to push; the browser countdown handles the alarm and
                # a returning tab reads the row. Mark as acknowledged after the
                # catch-up window so the list clears.
                for t in timers:
                    logger.info("WebApp timer expired: %s", t["name"])
                continue
            try:
                await self._deliver_voice(channel, timers)
            except Exception as exc:
                logger.error("Voice timer delivery failed for %s: %s", channel, exc)

    async def _deliver_voice(self, channel: str, timers: list[dict]) -> None:
        """Start the melody on the setting device via HA and schedule its stop.

        `channel` is the device key from device-mapping.yaml, stored as
        'esphome:<Raum>' or 'esphome'. The media_player entity for the device
        is resolved from alice.ha_entities by area, or from the
        TIMER_MEDIA_PLAYER_MAP override.
        """
        if not HA_TOKEN:
            logger.warning("HA_TOKEN missing — cannot deliver voice timer")
            return

        media_player = await self._media_player_for(channel)
        if not media_player:
            logger.warning(
                "No media_player for timer channel %s — timer marked expired, "
                "will announce on next contact", channel
            )
            return

        names = [t["name"] for t in timers]
        logger.info("Voice timer melody: device=%s timers=%s", channel, names)

        headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Signal the companion HA automation to start the melody. It owns
            # the loop + the "stop when the satellite is addressed" logic that
            # Alice cannot see. >>> HARDWARE-VERIFY.
            try:
                await client.post(
                    f"{HA_URL}/api/services/script/turn_on",
                    json={
                        "entity_id": HA_MELODY_START_SCRIPT,
                        "variables": {
                            "media_player": media_player,
                            "max_seconds": MELODY_MAX_SECONDS,
                        },
                    },
                    headers=headers,
                )
            except Exception as exc:
                logger.error("Melody start call failed: %s", exc)

        # After the max time, mark the collected timers acknowledged if they
        # are still 'expired' (nobody addressed the device).
        asyncio.create_task(self._auto_acknowledge([t["id"] for t in timers]))

    async def stop_melody(self, channel: str) -> None:
        """Stop a melody already playing for `channel` — used when a timer is
        deleted while its expiry alarm is still active (spec: delete beats a
        not-yet-acknowledged expiry).
        """
        if not HA_TOKEN:
            return
        media_player = await self._media_player_for(channel)
        headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{HA_URL}/api/services/script/turn_on",
                    json={
                        "entity_id": HA_MELODY_STOP_SCRIPT,
                        "variables": {"media_player": media_player} if media_player else {},
                    },
                    headers=headers,
                )
        except Exception as exc:
            logger.warning("Melody stop call failed for %s: %s", channel, exc)

    async def _auto_acknowledge(self, timer_ids: list) -> None:
        await asyncio.sleep(MELODY_MAX_SECONDS)
        try:
            await self._pool().execute(
                "UPDATE alice.timers SET status = 'acknowledged' "
                "WHERE id = ANY($1::uuid[]) AND status = 'expired'",
                [str(i) for i in timer_ids],
            )
        except Exception as exc:
            logger.warning("Auto-acknowledge failed: %s", exc)

    async def _media_player_for(self, channel: str) -> str | None:
        """Resolve the HA media_player entity for a timer's origin device."""
        # Explicit override map: "esphome:Büro=media_player.voice_pe_buero,..."
        raw = os.environ.get("TIMER_MEDIA_PLAYER_MAP", "")
        for pair in raw.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                if k.strip() == channel:
                    return v.strip()
        # Otherwise: the first media_player entity in the device's room.
        room = channel.split(":", 1)[1] if ":" in channel else None
        if not room:
            return None
        try:
            row = await self._pool().fetchrow(
                "SELECT entity_id FROM alice.ha_entities "
                "WHERE domain = 'media_player' AND is_active = TRUE "
                "AND LOWER(area_name) = LOWER($1) ORDER BY entity_id LIMIT 1",
                room.replace("_", " "),
            )
        except Exception as exc:
            logger.warning("media_player lookup failed: %s", exc)
            return None
        return row["entity_id"] if row else None


# ---------------------------------------------------------------------------
# Voice-PE announcement lookup (called by the /stream/timers/pending endpoint
# that alice-speech-gateway polls when a wakeword lands after a melody).
# ---------------------------------------------------------------------------
async def pending_announcement(pool, channel: str) -> str | None:
    """German sentence naming every expired-but-unannounced timer of a device,
    then mark them acknowledged. None when there is nothing to announce."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                "SELECT id, name FROM alice.timers "
                "WHERE origin_channel = $1 AND status = 'expired' "
                "FOR UPDATE",
                channel,
            )
            if not rows:
                return None
            await conn.execute(
                "UPDATE alice.timers SET status = 'acknowledged' "
                "WHERE id = ANY($1::uuid[])",
                [str(r["id"]) for r in rows],
            )
    names = [r["name"] for r in rows]
    if len(names) == 1:
        return f"Der {names[0]} ist abgelaufen."
    joined = " und ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 2 else " und ".join(names)
    return f"Der {joined} sind abgelaufen."
