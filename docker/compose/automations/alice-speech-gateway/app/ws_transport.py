"""
WebSocket transport — WebApp endpoints on port 10301.

  /ws/stt    Mode 1 — streaming transcription only (no AI, no TTS): rolling
             interim transcripts while recording, one final transcript on
             end_of_utterance.
  /ws/voice  Mode 2 — full voice conversation with sentence-streamed TTS,
             barge-in, and continued conversation.

Wire protocol (both endpoints):
  - JSON text frames carry control messages: {"type": "..."} .
  - Binary frames carry streamed audio bytes (250 ms chunks).

Auth: JWT via `Authorization: Bearer` header or `?token=` query parameter,
validated on the handshake before any audio is processed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import auth, config
from .audio_decode import WebmPcmDecoder
from .barge_in import BargeInController
from .pipeline import STATUS_LISTENING, STATUS_SESSION_ENDED, VoicePipeline
from .stt import STTError, get_engine
from .tts import TTSError

logger = logging.getLogger("alice-speech-gateway.ws")

router = APIRouter()

# 16 kHz / mono / s16le → 32 000 bytes per second of audio. The barge-in
# VAD needs at least a few hundred milliseconds to compute a meaningful
# voiced-frame ratio; 0.5 s gives ~16 VAD frames at 30 ms each.
_PCM_BYTES_PER_SEC = 16000 * 2
_BARGE_IN_PCM_MIN_BYTES = _PCM_BYTES_PER_SEC // 2

# Control words that should abort a turn without starting a new LLM query.
# Matches the fallback list in config.load_interrupt_phrases() — update both
# if interrupt-phrases.yaml changes significantly.
_STOP_WORDS = frozenset(["stop", "stopp", "halt", "warte", "moment"])


def _is_stop_only(transcript: str) -> bool:
    """True when the barge-in transcript is only a control word with no actionable content."""
    return transcript.strip().rstrip(".!?,").lower() in _STOP_WORDS


async def _authenticate(ws: WebSocket) -> dict | None:
    """Verify the JWT from the handshake. Closes the socket and returns None on failure."""
    token = auth.extract_ws_token(dict(ws.headers), dict(ws.query_params))
    try:
        return auth.verify_token(token)
    except auth.AuthError as exc:
        await ws.close(code=4401, reason=str(exc))
        logger.warning("WS auth rejected: %s", exc)
        return None


# Mode 1 streaming STT: re-transcribe the accumulated buffer at most this
# often while recording, so the client gets rolling interim results without
# a Whisper run per 250 ms chunk. In production the chunks arrive in real
# time, so this wall-clock interval tracks ~2 s of accumulated audio.
_STT_INTERIM_INTERVAL_S = 2.0


async def _stt_transcribe(audio: bytes) -> str | None:
    """Transcribe the accumulated WebM buffer; return None on STT failure.

    The buffer always starts at the first MediaRecorder chunk, which carries
    the EBML/Init header, so the partial stream stays decodable on every call.
    That is why Mode 1 re-transcribes the whole growing buffer instead of the
    latest chunk alone (continuation chunks lack the header). Mode-1 clips are
    short (< 30 s), so re-running Whisper on the buffer is cheap enough.
    """
    try:
        return await get_engine().transcribe(audio, config.SPEECH_LANGUAGE)
    except STTError:
        return None


@router.websocket("/ws/stt")
async def ws_stt(ws: WebSocket) -> None:
    """Mode 1 — streaming transcription only (no AI, no TTS).

    The client streams 250 ms WebM chunks as binary frames and signals the
    end of speech with a `{"type":"end_of_utterance"}` control frame. The
    gateway emits rolling `{"type":"interim"}` updates while recording and a
    single authoritative `{"type":"final"}` before closing the socket.
    """
    await ws.accept()
    payload = await _authenticate(ws)
    if payload is None:
        return
    log = {"user_id": payload["user_id"], "mode": "stt"}
    try:
        await _stt_loop(ws, log)
    except WebSocketDisconnect:
        logger.info("STT client disconnected", extra=log)


async def _stt_loop(ws: WebSocket, log: dict) -> None:
    """Accumulate streamed audio, emit interim transcripts, finalise on stop."""
    loop = asyncio.get_running_loop()
    buffer = bytearray()
    interim_task: asyncio.Task | None = None
    # Anchor the throttle to "now" so the first interim fires after ~2 s of
    # audio rather than on the very first 250 ms chunk.
    last_interim_at = loop.time()

    async def run_interim(snapshot: bytes) -> None:
        text = await _stt_transcribe(snapshot)
        # Skip empty/failed interim — an empty interim would blank the client
        # textarea mid-dictation. The final transcript is authoritative.
        if text:
            await ws.send_json({"type": "interim", "text": text})

    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                return

            audio = message.get("bytes")
            if audio is not None:
                buffer.extend(audio)
                now = loop.time()
                # One interim in flight at a time, throttled to the interval.
                if (
                    (interim_task is None or interim_task.done())
                    and now - last_interim_at >= _STT_INTERIM_INTERVAL_S
                ):
                    last_interim_at = now
                    interim_task = asyncio.create_task(run_interim(bytes(buffer)))
                continue

            text = message.get("text")
            if text is None:
                continue
            try:
                control = json.loads(text)
            except json.JSONDecodeError:
                continue
            if control.get("type") != "end_of_utterance":
                continue

            # Final transcript is authoritative — drop any in-flight interim.
            if interim_task is not None and not interim_task.done():
                interim_task.cancel()
            final = await _stt_transcribe(bytes(buffer))
            if final is None:
                await ws.send_json(
                    {"type": "error", "message": config.SPEECH_ERRORS["stt_failed"]}
                )
            else:
                await ws.send_json({"type": "final", "text": final})
            await ws.close(code=1000)
            return
    finally:
        if interim_task is not None and not interim_task.done():
            interim_task.cancel()


@router.websocket("/ws/voice")
async def ws_voice(ws: WebSocket) -> None:
    """Mode 2 — full voice conversation. Continuous audio in, TTS audio out."""
    await ws.accept()
    payload = await _authenticate(ws)
    if payload is None:
        return
    user_id = payload["user_id"]
    token = auth.extract_ws_token(dict(ws.headers), dict(ws.query_params))
    session_id = str(uuid.uuid4())
    log = {"session_id": session_id, "user_id": user_id, "mode": "voice"}
    logger.info("Voice session started", extra=log)

    async def send_status(status: str) -> None:
        await ws.send_json({"type": "status", "status": status})

    async def send_audio(chunk: bytes) -> None:
        await ws.send_bytes(chunk)

    async def send_audio_format(rate: int) -> None:
        await ws.send_json({"type": "audio_format", "rate": rate})

    pipeline = VoicePipeline(
        session_id=session_id,
        user_id=user_id,
        jwt_token=token or "",
        stt=get_engine(),
        send_status=send_status,
        send_audio=send_audio,
        send_audio_format=send_audio_format,
    )
    barge_in = BargeInController(get_engine())
    decoder = WebmPcmDecoder()
    try:
        await decoder.start()
    except FileNotFoundError:
        logger.error("ffmpeg not found — barge-in disabled for this session", extra=log)
        decoder = None  # type: ignore[assignment]

    await ws.send_json({"type": "session", "session_id": session_id})

    try:
        await _voice_loop(ws, pipeline, barge_in, log, decoder=decoder)
    except WebSocketDisconnect:
        logger.info("Voice client disconnected mid-stream", extra=log)
    except TTSError as exc:
        # BUG-5: a Piper outage cannot be reported as spoken audio. Per the
        # spec (Fehlerbehandlung) we log it and close the socket cleanly
        # instead of letting the exception escape the handler.
        logger.error("Voice session aborted — Piper unavailable: %s", exc, extra=log)
        try:
            await ws.close(code=1011, reason="TTS unavailable")
        except RuntimeError:
            pass  # socket already closed
    finally:
        if decoder is not None:
            await decoder.close()
        logger.info("Voice session ended", extra=log)


# Sentinels returned by the audio receiver.
_CLOSED = object()
_SESSION_END = object()


async def _voice_loop(
    ws: WebSocket,
    pipeline: VoicePipeline,
    barge_in: BargeInController,
    log: dict,
    decoder: WebmPcmDecoder | None = None,
) -> None:
    """
    Continued-conversation loop with live barge-in.

    A single receiver task continuously reads frames from the socket. When
    no turn is running, audio frames accumulate into an utterance that is
    flushed on an `end_of_utterance` control frame. While a turn IS running,
    incoming audio is routed to the barge-in path instead: chunks are fed
    to a persistent ffmpeg decoder and the resulting PCM is evaluated by
    the 3-stage `BargeInController`. A match interrupts the running
    pipeline and the interrupt transcript is fed straight back in as the
    next turn's input (same session_id).

    `decoder` is the per-session webm/opus → PCM stream decoder. None
    disables the barge-in path (e.g. when ffmpeg is unavailable in the
    container, or in tests that inject their own decoder via `state`).

    The session ends on silence timeout, an explicit `stop`, a client
    disconnect, or a `conversation_end` event from alice-chat-stream.
    """
    # Shared state between the receiver task and the turn driver.
    state = _VoiceState(decoder=decoder)

    receiver = asyncio.create_task(_audio_receiver(ws, barge_in, state, log))
    try:
        while True:
            # Wait for either a completed utterance or a session-ending event.
            outcome = await state.next_utterance()
            if outcome is _CLOSED:
                return
            if outcome is _SESSION_END:
                await _end_session(ws, log, "session ended")
                return

            audio_format, utterance = outcome  # type: ignore[misc]
            result = await _run_turn_with_barge_in(
                pipeline, state, utterance, log, audio_format=audio_format
            )
            # conversation_ended is intentionally ignored here: the WebApp voice
            # session stays open after HA commands so the user can continue
            # talking. The Wyoming path (wyoming_transport.py) ends its session
            # on conversation_ended — behaviour differs by design.
            #
            # Signal the client to transition back to listening. Without this
            # the client stays in "speaking" and its silence detector never fires.
            await ws.send_json({"type": "status", "status": STATUS_LISTENING})
    finally:
        receiver.cancel()
        try:
            await receiver
        except asyncio.CancelledError:
            pass


async def _run_turn_with_barge_in(
    pipeline: VoicePipeline,
    state: "_VoiceState",
    utterance: bytes,
    log: dict,
    audio_format: str = "webm",
):
    """
    Run one pipeline turn while the receiver feeds barge-in audio.

    If the receiver detects an interrupt during the turn, the running
    pipeline is cancelled and the interrupt transcript is run as a new
    turn — looping until a turn completes without interruption.
    """
    state.begin_turn(pipeline)
    try:
        result = await pipeline.run_turn(utterance, audio_format=audio_format)
        # An interrupt may have fired during the turn; chain interrupt turns
        # until one finishes cleanly. The session_id is preserved throughout.
        while result.interrupted:
            transcript = state.take_interrupt_transcript()
            if transcript is None:
                break
            if _is_stop_only(transcript):
                # Pure control word — user wants to abort, not start a new query.
                # Feeding "stop"/"warte" to the LLM causes unintended HA commands.
                logger.info("Barge-in stop-only: aborting turn without LLM query", extra=log)
                break
            logger.info("Feeding barge-in transcript as new turn", extra=log)
            result = await pipeline.run_text_turn(transcript)
        return result
    finally:
        state.end_turn()


async def _audio_receiver(
    ws: WebSocket,
    barge_in: BargeInController,
    state: "_VoiceState",
    log: dict,
) -> None:
    """
    Single task that owns `ws.receive()` for the whole session.

    When idle it accumulates an utterance and flushes it on
    `end_of_utterance`. When a turn is running it routes audio to the
    barge-in evaluator and, on a match, interrupts the running pipeline.
    """
    while True:
        try:
            message = await asyncio.wait_for(
                ws.receive(), timeout=config.SILENCE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            if state.turn_running():
                # A turn is in progress — the timeout is not silence.
                continue
            logger.info("Voice session silence timeout", extra=log)
            state.signal(_SESSION_END)
            return

        if message.get("type") == "websocket.disconnect":
            state.signal(_CLOSED)
            return

        if message.get("bytes") is not None:
            audio = message["bytes"]
            # Always feed the streaming decoder so it builds a continuous
            # PCM view of the conversation (MediaRecorder chunks after
            # the first lack EBML headers and cannot be decoded alone).
            if state.decoder is not None:
                await state.decoder.feed(audio)
            if state.turn_running():
                # Barge-in path: pull decoded PCM and evaluate.
                await _evaluate_barge_in(barge_in, state, log)
            else:
                state.utterance.extend(audio)
                # Pull decoded PCM for the utterance STT path. Using the
                # decoder's output avoids the WebM init-header problem:
                # continuation chunks (2nd+ utterances) lack the EBML header
                # and fail standalone decoding. The decoder has full stream
                # context and produces valid PCM for every utterance.
                if state.decoder is not None:
                    state.pcm_utterance.extend(state.decoder.take_pcm())
            continue

        if message.get("text") is not None:
            try:
                control = json.loads(message["text"])
            except json.JSONDecodeError:
                continue
            ctype = control.get("type")
            if ctype == "stop":
                state.stop_turn()  # abort any running pipeline immediately
                state.signal(_SESSION_END)
                return
            if ctype == "end_of_utterance" and not state.turn_running():
                state.flush_utterance()


async def _evaluate_barge_in(
    barge_in: BargeInController,
    state: "_VoiceState",
    log: dict,
) -> None:
    """
    Pull decoded PCM from the per-session decoder and run it through the
    3-stage barge-in controller.

    The PCM is accumulated in `state.barge_pcm_buffer` until at least
    ~0.5 s is available so the VAD can compute a meaningful voiced-frame
    ratio. On an interrupt match the running pipeline is cancelled and
    the transcript handed to the turn driver.
    """
    if state.interrupt_pending():
        return  # an interrupt is already being processed — ignore further audio
    if state.decoder is None:
        return  # ffmpeg unavailable — barge-in disabled for this session

    state.barge_pcm_buffer.extend(state.decoder.take_pcm())
    if len(state.barge_pcm_buffer) < _BARGE_IN_PCM_MIN_BYTES:
        return

    pcm_segment = bytes(state.barge_pcm_buffer)
    state.barge_pcm_buffer.clear()

    # Pass `webm=None` so the controller wraps the PCM in a WAV container
    # for Whisper's ffmpeg-based auto-detection (raw webm chunks captured
    # mid-stream don't have the EBML init segment and aren't decodable
    # standalone).
    transcript = await barge_in.evaluate(pcm=pcm_segment, webm=None)
    if transcript is None:
        return  # silence / noise / no interrupt intent — pipeline continues

    logger.info("Barge-in interrupt accepted: %r", transcript, extra=log)
    state.trigger_interrupt(transcript)


class _VoiceState:
    """
    Shared state between the audio receiver task and the turn driver.

    Holds the in-progress utterance buffer, the barge-in PCM accumulator,
    the per-session webm→PCM decoder, the currently running pipeline (if
    any), and a queue used to hand completed utterances / session-ending
    sentinels to the turn driver.
    """

    def __init__(self, decoder: WebmPcmDecoder | None = None) -> None:
        self.utterance = bytearray()            # WebM bytes (fallback when decoder absent)
        self.pcm_utterance = bytearray()        # decoded PCM from the per-session decoder
        self.barge_pcm_buffer = bytearray()
        self.decoder = decoder
        self._events: asyncio.Queue = asyncio.Queue()
        self._pipeline: VoicePipeline | None = None
        self._interrupt_transcript: str | None = None

    # --- turn lifecycle ---
    def begin_turn(self, pipeline: VoicePipeline) -> None:
        self._pipeline = pipeline
        self.barge_pcm_buffer.clear()
        # Discard PCM produced during the (now-finished) user utterance
        # — it isn't barge-in audio.
        if self.decoder is not None:
            self.decoder.discard_pcm()

    def end_turn(self) -> None:
        self._pipeline = None
        self._interrupt_transcript = None
        self.barge_pcm_buffer.clear()
        if self.decoder is not None:
            self.decoder.discard_pcm()

    def turn_running(self) -> bool:
        return self._pipeline is not None

    # --- barge-in ---
    def stop_turn(self) -> None:
        """Interrupt the running pipeline so a stop request takes effect immediately."""
        if self._pipeline is not None:
            self._pipeline.interrupt()

    def trigger_interrupt(self, transcript: str) -> None:
        """Cancel the running pipeline and stash the interrupt transcript."""
        self._interrupt_transcript = transcript
        if self._pipeline is not None:
            self._pipeline.interrupt()

    def interrupt_pending(self) -> bool:
        return self._interrupt_transcript is not None

    def take_interrupt_transcript(self) -> str | None:
        transcript = self._interrupt_transcript
        self._interrupt_transcript = None
        return transcript

    # --- utterance / event handoff ---
    def flush_utterance(self) -> None:
        # Drain any final PCM that ffmpeg has decoded but not yet emitted.
        if self.decoder is not None:
            self.pcm_utterance.extend(self.decoder.take_pcm())

        if self.pcm_utterance:
            # Happy path: PCM available from the per-session decoder.
            # Continuation WebM chunks (2nd+ utterances) lack the EBML init
            # header and fail standalone decoding — PCM sidesteps this.
            audio = bytes(self.pcm_utterance)
            self.pcm_utterance = bytearray()
            self.utterance = bytearray()
            self._events.put_nowait(("pcm", audio))
        else:
            # Fallback: ffmpeg unavailable or produced no output yet.
            # Only the first utterance (full WebM with header) is safe here.
            audio = bytes(self.utterance)
            self.utterance = bytearray()
            self._events.put_nowait(("webm", audio))

    def signal(self, sentinel: object) -> None:
        self._events.put_nowait(sentinel)

    async def next_utterance(self):
        """Block until the receiver delivers an utterance or a sentinel."""
        return await self._events.get()


async def _end_session(ws: WebSocket, log: dict, reason: str) -> None:
    await ws.send_json({"type": "status", "status": STATUS_SESSION_ENDED})
    logger.info("Voice session closing: %s", reason, extra=log)
    await ws.close(code=1000, reason=reason)
