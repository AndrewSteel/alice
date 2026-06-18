"""
Wyoming transport — HA Voice Device endpoint on port 10300.

Handles direct Wyoming connections from ESPHome devices after wakeword
detection. The gateway runs the full-voice pipeline (faster-whisper STT →
alice-chat-stream → Piper TTS) and streams audio back over Wyoming protocol.

PROJ-43 additions:
  - Per-turn Speaker-ID: STT + Speaker-ID run in parallel on every turn.
    The identified user's JWT is used for the alice-chat-stream call.
  - First-turn greeting replaces the wake sound.
  - Enrollment state machine: triggered by specific phrases spoken by an
    identified admin; creates the new user in alice.users.
  - device-mapping.yaml: user_id field removed (identity from Speaker-ID).

Continued conversation: after each TTS response the session stays open and
waits for the next AudioStart/AudioStop cycle. The session ends on a
conversation_end signal from alice-chat-stream, a silence timeout, a Piper
outage, or a device disconnect.

Auth: no JWT from the device. The Wyoming port is only reachable inside the
Docker network. The source IP is mapped to device name/room via
device-mapping.yaml; unknown IPs get a spoken error and no AI call.
"""
from __future__ import annotations

import asyncio
import io
import logging
import uuid
import wave as _wave
from typing import Optional

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler, AsyncServer

from . import config, tts
from .pipeline import VoicePipeline
from .stt import STTError, get_engine

logger = logging.getLogger("alice-speech-gateway.wyoming")

_SAMPLE_RATE = 48000
_SAMPLE_WIDTH = 2
_CHANNELS = 1
_MAX_DEVICE_CHUNK = 4096
_BYTES_PER_SEC = _SAMPLE_RATE * _SAMPLE_WIDTH * _CHANNELS  # 96 000 B/s at 48 kHz


def _pcm_to_wav(pcm: bytes, *, rate: int, channels: int, sampwidth: int) -> bytes:
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class GatewayWyomingHandler(AsyncEventHandler):
    """One handler instance per HA Voice Device connection."""

    def __init__(self, *args, device_mapping: dict[str, config.Device], wyoming_info: Info, **kwargs):
        super().__init__(*args, **kwargs)
        self._device_mapping = device_mapping
        self._info = wyoming_info
        peername = self.writer.get_extra_info("peername")
        self._client_ip: str = peername[0] if peername else ""
        self._event_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._loop_task: asyncio.Task | None = None

    async def handle_event(self, event: Event) -> bool:
        if self._loop_task is not None and self._loop_task.done():
            return False

        if not AudioChunk.is_type(event.type):
            logger.debug(
                "Wyoming event: type=%r data=%r client_ip=%s",
                event.type, event.data, self._client_ip,
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
        from . import enrollment as enroll_mod
        from . import speaker_db
        from . import speaker_id as sid_mod

        session_id = str(uuid.uuid4())
        device = self._device_mapping.get(self._client_ip)
        device_label = device.name if device else self._client_ip
        pipeline: Optional[VoicePipeline] = None
        turn_count = 0
        active_enrollment: Optional[enroll_mod.EnrollmentSession] = None

        # Load enrolled voice profiles once per session
        speaker_profiles: list[dict] = []
        if speaker_db.is_ready():
            try:
                speaker_profiles = await speaker_db.load_all_profiles()
            except Exception as exc:
                logger.warning("Could not load speaker profiles: %s", exc)

        while True:
            collected = await self._collect_audio()
            if collected is None:
                logger.info(
                    "Wyoming silence timeout — session ending",
                    extra={"session_id": session_id, "device": device_label},
                )
                break
            audio_pcm, pcm_rate, pcm_width, pcm_channels = collected

            if device is None:
                logger.warning("Unknown Wyoming client IP: %r", self._client_ip)
                await self._speak_error(config.SPEECH_ERRORS["unknown_device"])
                continue

            if len(audio_pcm) < pcm_rate * pcm_width * config.MIN_AUDIO_SECONDS:
                await self._speak_error(config.SPEECH_ERRORS["audio_too_short"])
                continue

            # Convert PCM → WAV once; reused for STT, Speaker-ID, and enrollment
            wav = _pcm_to_wav(audio_pcm, rate=pcm_rate, channels=pcm_channels, sampwidth=pcm_width)

            # --- Enrollment turn: feed audio to state machine ---
            if active_enrollment is not None:
                still_active = await self._run_enrollment_turn(
                    active_enrollment, wav, speaker_profiles
                )
                if not still_active:
                    active_enrollment = None
                continue

            # --- Run STT + Speaker-ID in parallel ---
            stt_task = asyncio.create_task(get_engine().transcribe(wav, config.SPEECH_LANGUAGE))

            speaker_task: Optional[asyncio.Task] = None
            if sid_mod.is_ready() and speaker_profiles:
                speaker_task = asyncio.create_task(
                    sid_mod.identify_from_audio(wav, speaker_profiles, config.SPEAKER_THRESHOLD)
                )

            try:
                transcript = await stt_task
            except STTError:
                if speaker_task:
                    speaker_task.cancel()
                await self._speak_error(config.SPEECH_ERRORS["stt_failed"])
                continue

            spk_user_id: Optional[str] = None
            spk_confidence: float = 0.0
            spk_display_name: Optional[str] = None
            if speaker_task is not None:
                try:
                    spk_user_id, spk_confidence, spk_display_name = await asyncio.wait_for(
                        speaker_task, timeout=2.0
                    )
                except (asyncio.TimeoutError, Exception) as exc:
                    logger.warning("Speaker-ID result discarded: %s", exc)

            if not transcript.strip():
                # Genuine silence — end session quietly (PROJ-42 Bug 4 fix)
                logger.info(
                    "Wyoming session ended — no speech detected",
                    extra={"session_id": session_id, "device": device_label},
                )
                break

            logger.info(
                "Wyoming STT: %r  speaker=%r conf=%.2f",
                transcript, spk_user_id, spk_confidence,
                extra={"session_id": session_id, "device": device.name},
            )

            # --- Enrollment trigger check (admin only, before AI call) ---
            is_trigger, enroll_role = enroll_mod.is_enrollment_intent(transcript)
            if is_trigger:
                if spk_user_id:
                    user_info = await speaker_db.get_user(spk_user_id)
                    if user_info and user_info.get("role") == "admin":
                        active_enrollment = enroll_mod.EnrollmentSession(
                            role=enroll_role,
                            username_checker=speaker_db.username_exists,
                        )
                        logger.info(
                            "Enrollment triggered by admin %s (role=%s)",
                            spk_user_id, enroll_role,
                        )
                        await self._speak_text(active_enrollment.first_prompt())
                        continue
                # Not admin or unrecognised → reject
                await self._speak_error(config.SPEECH_ERRORS["enrollment_not_admin"])
                continue

            # --- Normal pipeline turn ---
            turn_count += 1
            is_first_turn = turn_count == 1

            if pipeline is None:
                pipeline = VoicePipeline(
                    session_id=session_id,
                    user_id=spk_user_id or "guest",
                    jwt_token=_token_for(spk_user_id),
                    stt=get_engine(),
                    send_status=self._noop_status,
                    send_audio=self._send_audio,
                    tts_target_rate=_SAMPLE_RATE,
                    device_id=(
                        device.room.replace(" ", "_") if device.room
                        else device.name.replace(" ", "_")
                    ),
                    jwt_factory=_service_token_for,
                )
                logger.info(
                    "Wyoming session start",
                    extra={
                        "session_id": session_id,
                        "user_id": spk_user_id or "guest",
                        "mode": "wyoming",
                        "device": device.name,
                        "room": device.room,
                        "client_ip": self._client_ip,
                    },
                )

            log = {
                "session_id": session_id,
                "mode": "wyoming",
                "device": device.name,
                "room": device.room,
            }
            logger.info(
                "Wyoming turn start (turn=%d speaker=%r conf=%.2f)",
                turn_count, spk_user_id, spk_confidence,
                extra=log,
            )

            await self.write_event(
                AudioStart(rate=_SAMPLE_RATE, width=_SAMPLE_WIDTH, channels=_CHANNELS).event()
            )
            try:
                result = await pipeline.run_text_turn(
                    transcript,
                    speaker_user_id=spk_user_id,
                    speaker_confidence=spk_confidence,
                    speaker_display_name=spk_display_name,
                    is_first_turn=is_first_turn,
                )
            except tts.TTSError:
                logger.error("Wyoming Piper unavailable — ending session", extra=log)
                break
            finally:
                await self.write_event(AudioStop().event())

            logger.info("Wyoming turn done", extra=log)

            if result.no_speech:
                logger.info("Wyoming session ended — no speech detected", extra=log)
                break

            if result.conversation_ended:
                logger.info("Wyoming conversation ended by AI signal", extra=log)
                break

        logger.info(
            "Wyoming session end",
            extra={"session_id": session_id, "device": device_label, "client_ip": self._client_ip},
        )
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass

    async def _run_enrollment_turn(
        self,
        session,
        wav: bytes,
        speaker_profiles: list[dict],
    ) -> bool:
        """
        Feed one turn to the enrollment state machine and speak the response.
        Returns True if enrollment is still in progress, False when done.
        """
        from . import speaker_db
        from . import speaker_id as sid_mod

        try:
            transcript = await get_engine().transcribe(wav, config.SPEECH_LANGUAGE)
        except STTError:
            transcript = ""

        prompt = await session.process_turn(transcript, wav)
        await self._speak_text(prompt)

        if not session.is_done:
            return True  # still going

        if session.succeeded:
            sample_audio_list = session.get_sample_audio()
            embeddings: list[list[float]] = []
            if sid_mod.is_ready():
                for sample_wav in sample_audio_list:
                    emb = await sid_mod.extract_embedding(sample_wav)
                    if emb is not None:
                        embeddings.append(emb.tolist())

            if embeddings:
                try:
                    await speaker_db.create_enrolled_user(
                        username=session.username,
                        display_name=session.display_name,
                        anrede=session.anrede,
                        sprache=session.sprache,
                        role=session.role,
                        embeddings=embeddings,
                    )
                    logger.info(
                        "Enrollment complete: %s (%d embeddings)", session.username, len(embeddings)
                    )
                    # Refresh profiles in-place so the new user is recognisable immediately
                    speaker_profiles.clear()
                    new_profiles = await speaker_db.load_all_profiles()
                    speaker_profiles.extend(new_profiles)
                except Exception as exc:
                    logger.error("Failed to save enrolled user: %s", exc)
            else:
                logger.warning("Enrollment %s: no embeddings extracted", session.username)

        return False  # done

    async def _collect_audio(self) -> tuple[bytes, int, int, int] | None:
        """Wait for one AudioStart/AudioChunk*/AudioStop block."""
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
        for offset in range(0, len(chunk), _MAX_DEVICE_CHUNK):
            data = chunk[offset : offset + _MAX_DEVICE_CHUNK]
            await self.write_event(
                AudioChunk(
                    rate=_SAMPLE_RATE, width=_SAMPLE_WIDTH, channels=_CHANNELS,
                    audio=data,
                ).event()
            )
            await asyncio.sleep(len(data) / _BYTES_PER_SEC)

    async def _speak_text(self, message: str) -> None:
        """Stream a spoken message to the device, framed as a Wyoming audio block."""
        await self.write_event(
            AudioStart(rate=_SAMPLE_RATE, width=_SAMPLE_WIDTH, channels=_CHANNELS).event()
        )
        try:
            async for chunk in tts.synthesize(message, target_rate=_SAMPLE_RATE):
                await self._send_audio(chunk)
        except tts.TTSError:
            logger.error("Cannot speak — Piper unavailable")
        finally:
            await self.write_event(AudioStop().event())

    async def _speak_error(self, message: str) -> None:
        await self._speak_text(message)

    async def _noop_status(self, _status: str) -> None:
        return


def _service_token_for(user_id: str) -> str:
    from .service_token import mint_service_token
    return mint_service_token(user_id)


def _token_for(user_id: Optional[str]) -> str:
    """Mint a service token for the identified speaker, or a guest placeholder."""
    from .service_token import mint_service_token
    return mint_service_token(user_id or "00000000-0000-0000-0000-000000000000")


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
