"""
Wyoming transport — HA Voice Device endpoint on port 10300.

Handles direct Wyoming connections from ESPHome devices after wakeword
detection. The gateway runs the full-voice pipeline (faster-whisper STT →
alice-chat-stream → Piper TTS) and streams audio back over Wyoming protocol.

Continued conversation: after each TTS response the session stays open and
waits for the next AudioStart/AudioStop cycle. The session ends on a
conversation_end signal from alice-chat-stream, a silence timeout, a Piper
outage, or a device disconnect.

Auth: no JWT. The Wyoming port is only reachable inside the Docker network.
The source IP of the TCP connection is mapped to an alice user_id (plus
name/room) via device-mapping.yaml; unknown IPs get a spoken error and no
AI call.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler, AsyncServer

from . import config, tts
from .pipeline import VoicePipeline
from .stt import get_engine

logger = logging.getLogger("alice-speech-gateway.wyoming")

# Audio delivered to the HA Voice PE device: 48 kHz mono 16-bit PCM.
# 48 kHz matches the I2S hardware rate so the device uses i2s_audio_speaker
# directly — no resampling chain with its ~6 s startup delay.
_SAMPLE_RATE = 48000
_SAMPLE_WIDTH = 2
_CHANNELS = 1
# Max audio payload per Wyoming AudioChunk event sent to the device.
# ESP32 rx_buffer_ is 16 KB; a single event (header ~190 B + payload) must fit.
_MAX_DEVICE_CHUNK = 4096
# Bytes per second at the target audio rate — used for send pacing.
_BYTES_PER_SEC = _SAMPLE_RATE * _SAMPLE_WIDTH * _CHANNELS  # 96 000 B/s at 48 kHz


class GatewayWyomingHandler(AsyncEventHandler):
    """One handler instance per HA Voice Device connection."""

    def __init__(self, *args, device_mapping: dict[str, config.Device], wyoming_info: Info, **kwargs):
        super().__init__(*args, **kwargs)
        self._device_mapping = device_mapping
        self._info = wyoming_info
        # Stable identifier: client IP extracted from the TCP connection.
        peername = self.writer.get_extra_info("peername")
        self._client_ip: str = peername[0] if peername else ""
        # Audio events are forwarded here so _conversation_loop can consume them.
        self._event_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._loop_task: asyncio.Task | None = None

    async def handle_event(self, event: Event) -> bool:
        # Session already ended — returning False signals the Wyoming server to
        # close this connection. This handles any late events that arrive after
        # _conversation_loop already closed the writer and exited.
        if self._loop_task is not None and self._loop_task.done():
            return False

        if not AudioChunk.is_type(event.type):
            logger.debug(
                "Wyoming event: type=%r data=%r client_ip=%s",
                event.type,
                event.data,
                self._client_ip,
            )

        if Describe.is_type(event.type):
            await self.write_event(self._info.event())
            return True

        if AudioStart.is_type(event.type) or AudioChunk.is_type(event.type) or AudioStop.is_type(event.type):
            if self._loop_task is None:
                self._loop_task = asyncio.create_task(self._conversation_loop())
            await self._event_queue.put(event)

        return True

    async def _conversation_loop(self) -> None:
        """Run a continued-conversation loop for this HA device connection."""
        session_id = str(uuid.uuid4())
        device = self._device_mapping.get(self._client_ip)
        device_label = device.name if device else self._client_ip
        pipeline: VoicePipeline | None = None
        turn_count = 0

        while True:
            collected = await self._collect_audio()
            if collected is None:
                logger.info(
                    "Wyoming silence timeout — session ending",
                    extra={"session_id": session_id, "device": device_label},
                )
                break
            audio, pcm_rate, pcm_width, pcm_channels = collected

            if device is None:
                logger.warning("Unknown Wyoming client IP: %r", self._client_ip)
                await self._speak_error(config.SPEECH_ERRORS["unknown_device"])
                continue

            if pipeline is None:
                pipeline = VoicePipeline(
                    session_id=session_id,
                    user_id=device.user_id,
                    jwt_token=_service_token_for(device.user_id),
                    stt=get_engine(),
                    send_status=self._noop_status,
                    send_audio=self._send_audio,
                    tts_target_rate=_SAMPLE_RATE,
                )
                logger.info(
                    "Wyoming session start",
                    extra={"session_id": session_id, "user_id": device.user_id,
                           "mode": "wyoming", "device": device.name, "room": device.room,
                           "client_ip": self._client_ip},
                )
            else:
                # BUG-2: re-mint the service token at the start of every turn.
                # A continued conversation can stay open far longer than the
                # token TTL (SERVICE_JWT_TTL_SECONDS, default 120 s); reusing the
                # session-start token would send an expired token on later turns
                # → 401 → spoken error mid-conversation. A single turn always
                # completes well within the TTL, so a fresh token per turn is safe.
                pipeline.set_jwt(_service_token_for(device.user_id))

            if len(audio) < pcm_rate * pcm_width * config.MIN_AUDIO_SECONDS:
                await self._speak_error(config.SPEECH_ERRORS["audio_too_short"])
                continue

            turn_count += 1
            log = {"session_id": session_id, "user_id": device.user_id,
                   "mode": "wyoming", "device": device.name, "room": device.room}
            logger.info("Wyoming turn start", extra=log)

            await self.write_event(
                AudioStart(rate=_SAMPLE_RATE, width=_SAMPLE_WIDTH, channels=_CHANNELS).event()
            )
            try:
                result = await pipeline.run_turn(
                    audio, audio_format="pcm",
                    pcm_rate=pcm_rate, pcm_width=pcm_width, pcm_channels=pcm_channels,
                    # Never speak an error on silence — wake-word accidental triggers
                    # should end quietly. The device handles UX via LED and the next
                    # wake-word cycle (user design decision, Bug 4 fix).
                    speak_on_empty=False,
                )
            except tts.TTSError:
                logger.error("Wyoming Piper unavailable — ending session", extra=log)
                break
            finally:
                await self.write_event(AudioStop().event())

            logger.info("Wyoming turn done", extra=log)

            if result.no_speech:
                # Whisper VAD removed all audio — genuine silence in the room.
                # End the session rather than looping: the user can trigger a
                # new session with the wake word when ready.
                logger.info("Wyoming session ended — no speech detected", extra=log)
                break

            if result.conversation_ended:
                logger.info("Wyoming conversation ended by AI signal", extra=log)
                break

        logger.info(
            "Wyoming session end",
            extra={"session_id": session_id, "device": device_label, "client_ip": self._client_ip},
        )
        # Close the TCP connection so the device transitions out of AWAIT_RESPONSE
        # back to IDLE (wake-word listening). Without this, the device polls
        # read_socket_() forever and can never receive a new wake-word session.
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass

    async def _collect_audio(self) -> tuple[bytes, int, int, int] | None:
        """Wait for one AudioStart/AudioChunk*/AudioStop block.

        Returns (pcm_bytes, rate, width, channels) as declared in the AudioStart
        event, or None if the silence timeout fires before an AudioStart arrives.
        """
        audio = bytearray()
        collecting = False
        rate, width, channels = _SAMPLE_RATE, _SAMPLE_WIDTH, _CHANNELS
        while True:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=config.SILENCE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return None

            if AudioStart.is_type(event.type):
                evt = AudioStart.from_event(event)
                rate, width, channels = evt.rate, evt.width, evt.channels
                audio.clear()
                collecting = True
            elif AudioChunk.is_type(event.type) and collecting:
                audio.extend(AudioChunk.from_event(event).audio)
            elif AudioStop.is_type(event.type) and collecting:
                return bytes(audio), rate, width, channels

    async def _send_audio(self, chunk: bytes) -> None:
        # Split into ≤ 4 KB chunks (rx_buffer_ constraint) and pace delivery to
        # match I2S playback speed. Without pacing the gateway sends at network
        # speed (>10× real-time), overflows the device's 200 ms ring buffer, and
        # all but the last ~200 ms of audio is silently dropped.
        for offset in range(0, len(chunk), _MAX_DEVICE_CHUNK):
            data = chunk[offset : offset + _MAX_DEVICE_CHUNK]
            await self.write_event(
                AudioChunk(
                    rate=_SAMPLE_RATE, width=_SAMPLE_WIDTH, channels=_CHANNELS,
                    audio=data,
                ).event()
            )
            await asyncio.sleep(len(data) / _BYTES_PER_SEC)

    async def _speak_error(self, message: str) -> None:
        """Stream a spoken error to the device, framed as a Wyoming audio block."""
        await self.write_event(
            AudioStart(rate=_SAMPLE_RATE, width=_SAMPLE_WIDTH, channels=_CHANNELS).event()
        )
        try:
            async for chunk in tts.synthesize(message, target_rate=_SAMPLE_RATE):
                await self._send_audio(chunk)
        except tts.TTSError:
            logger.error("Cannot speak Wyoming error — Piper unavailable")
        finally:
            await self.write_event(AudioStop().event())

    async def _noop_status(self, _status: str) -> None:
        return


def _service_token_for(user_id: str) -> str:
    """
    Mint a short-lived RS256 JWT for the mapped user.

    The Wyoming endpoint has no client-supplied token, but alice-chat-stream
    still requires one. We sign a service token with the same key pair.
    Wired lazily so the module imports without the private key present.
    """
    from .service_token import mint_service_token

    return mint_service_token(user_id)


async def run_wyoming_server(device_mapping: dict[str, config.Device], wyoming_info: Info) -> None:
    """Start the Wyoming TCP server. Runs for the app lifetime."""
    uri = f"tcp://0.0.0.0:{config.WYOMING_PORT}"
    server = AsyncServer.from_uri(uri)
    logger.info("Wyoming server listening on %s", uri)

    def _handler_factory(*args, **kwargs):
        return GatewayWyomingHandler(
            *args, device_mapping=device_mapping, wyoming_info=wyoming_info, **kwargs
        )

    await server.run(_handler_factory)
