"""
Wyoming transport — HA Voice Device endpoint on port 10300 (Mode 3).

Replaces the wyoming-whisper container. HA Voice Devices connect after
wakeword detection and stream audio; the gateway runs the same full-voice
pipeline as Mode 2 and streams TTS audio back over the Wyoming protocol.

Continued conversation: after each TTS response the session stays open and
waits for the next AudioStart/AudioStop cycle. The session ends on a
conversation_end signal from alice-chat-stream, a silence timeout, a Piper
outage, or a device disconnect.

Auth: no JWT. The Wyoming port is only reachable inside the Docker network.
The device id from the Wyoming `Info`/`RunPipeline` metadata is mapped to
an alice user_id via device-mapping.yaml; unknown devices get a spoken
error and no AI call.
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

# Standard Wyoming audio: 16 kHz mono 16-bit PCM.
_SAMPLE_RATE = 16000
_SAMPLE_WIDTH = 2
_CHANNELS = 1


class GatewayWyomingHandler(AsyncEventHandler):
    """One handler instance per HA Voice Device connection."""

    def __init__(self, *args, device_mapping: dict[str, str], wyoming_info: Info, **kwargs):
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
        pipeline: VoicePipeline | None = None

        while True:
            audio = await self._collect_audio()
            if audio is None:
                logger.info(
                    "Wyoming silence timeout — session ending",
                    extra={"session_id": session_id, "device_id": self._device_id},
                )
                break

            user_id = self._device_mapping.get(self._client_ip)
            if user_id is None:
                logger.warning("Unknown Wyoming client IP: %r", self._client_ip)
                await self._speak_error(config.SPEECH_ERRORS["unknown_device"])
                continue

            if pipeline is None:
                pipeline = VoicePipeline(
                    session_id=session_id,
                    user_id=user_id,
                    jwt_token=_service_token_for(user_id),
                    stt=get_engine(),
                    send_status=self._noop_status,
                    send_audio=self._send_audio,
                )
                logger.info(
                    "Wyoming session start",
                    extra={"session_id": session_id, "user_id": user_id,
                           "mode": "wyoming", "client_ip": self._client_ip},
                )

            if len(audio) < _SAMPLE_RATE * _SAMPLE_WIDTH * config.MIN_AUDIO_SECONDS:
                await self._speak_error(config.SPEECH_ERRORS["audio_too_short"])
                continue

            log = {"session_id": session_id, "user_id": user_id,
                   "mode": "wyoming", "client_ip": self._client_ip}
            logger.info("Wyoming turn start", extra=log)

            await self.write_event(
                AudioStart(rate=_SAMPLE_RATE, width=_SAMPLE_WIDTH, channels=_CHANNELS).event()
            )
            try:
                result = await pipeline.run_turn(audio, audio_format="pcm")
            except tts.TTSError:
                logger.error("Wyoming Piper unavailable — ending session", extra=log)
                break
            finally:
                await self.write_event(AudioStop().event())

            logger.info("Wyoming turn done", extra=log)

            if result.conversation_ended:
                logger.info("Wyoming conversation ended by AI signal", extra=log)
                break

        logger.info(
            "Wyoming session end",
            extra={"session_id": session_id, "client_ip": self._client_ip},
        )

    async def _collect_audio(self) -> bytes | None:
        """Wait for one AudioStart/AudioChunk*/AudioStop block.

        Returns collected PCM bytes, or None if the silence timeout fires
        before an AudioStart arrives.
        """
        audio = bytearray()
        collecting = False
        while True:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=config.SILENCE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return None

            if AudioStart.is_type(event.type):
                audio.clear()
                collecting = True
            elif AudioChunk.is_type(event.type) and collecting:
                audio.extend(AudioChunk.from_event(event).audio)
            elif AudioStop.is_type(event.type) and collecting:
                return bytes(audio)

    async def _send_audio(self, chunk: bytes) -> None:
        await self.write_event(
            AudioChunk(
                rate=_SAMPLE_RATE, width=_SAMPLE_WIDTH, channels=_CHANNELS, audio=chunk
            ).event()
        )

    async def _speak_error(self, message: str) -> None:
        """Stream a spoken error to the device, framed as a Wyoming audio block."""
        await self.write_event(
            AudioStart(rate=_SAMPLE_RATE, width=_SAMPLE_WIDTH, channels=_CHANNELS).event()
        )
        try:
            async for chunk in tts.synthesize(message):
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


async def run_wyoming_server(device_mapping: dict[str, str], wyoming_info: Info) -> None:
    """Start the Wyoming TCP server. Runs for the app lifetime."""
    uri = f"tcp://0.0.0.0:{config.WYOMING_PORT}"
    server = AsyncServer.from_uri(uri)
    logger.info("Wyoming server listening on %s", uri)

    def _handler_factory(*args, **kwargs):
        return GatewayWyomingHandler(
            *args, device_mapping=device_mapping, wyoming_info=wyoming_info, **kwargs
        )

    await server.run(_handler_factory)
