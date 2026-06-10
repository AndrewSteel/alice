"""
VoicePipeline — one instance per active voice session (Mode 2 + 3).

Flow per user utterance:
    STT → alice-chat-stream (SSE) → SentenceAccumulator → wyoming-piper
    → audio chunks streamed to the client.

Sentence-level streaming: a sentence is sent to Piper the moment it is
complete, so TTS starts before the LLM finishes. Barge-in is handled by
the transport layer (it owns the audio socket) which calls `interrupt()`.

The pipeline is transport-agnostic: callers provide `send_status` and
`send_audio` callbacks plus a `speak_error` helper, so the same pipeline
serves both the WebSocket transport and the Wyoming transport.
"""
from __future__ import annotations

import asyncio
import io
import logging
import wave as _wave
from typing import Awaitable, Callable

from . import config, tts
from .chat_client import ChatError, ChatTimeout, stream_reply
from .sentence_accumulator import SentenceAccumulator
from .stt import STTEngine, STTError

logger = logging.getLogger("alice-speech-gateway.pipeline")


def _pcm_to_wav(pcm: bytes, *, rate: int = 16000, channels: int = 1, sampwidth: int = 2) -> bytes:
    """Wrap raw PCM bytes in a WAV container so ffmpeg/Whisper can detect the format."""
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()

SendStatus = Callable[[str], Awaitable[None]]
SendAudio = Callable[[bytes], Awaitable[None]]

# Status events surfaced to the WebApp client (spec: Continued Conversation).
STATUS_STT_COMPLETE = "stt_complete"
STATUS_AI_PROCESSING = "ai_processing"
STATUS_TTS_GENERATING = "tts_generating"
STATUS_SESSION_ENDED = "session_ended"


class PipelineResult:
    """Outcome of one utterance turn."""

    __slots__ = ("conversation_ended", "interrupted", "no_speech")

    def __init__(
        self,
        conversation_ended: bool = False,
        interrupted: bool = False,
        no_speech: bool = False,
    ) -> None:
        self.conversation_ended = conversation_ended
        self.interrupted = interrupted
        # True when Whisper VAD removed all audio — genuine silence, not a
        # transcription ambiguity. The Wyoming handler uses this to end the
        # session rather than looping back into continued-conversation.
        self.no_speech = no_speech


class VoicePipeline:
    """Stateful per-session pipeline. Reused across turns of one conversation."""

    def __init__(
        self,
        session_id: str,
        user_id: str,
        jwt_token: str,
        stt: STTEngine,
        send_status: SendStatus,
        send_audio: SendAudio,
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self._jwt = jwt_token
        self._stt = stt
        self._send_status = send_status
        self._send_audio = send_audio
        self._interrupt = asyncio.Event()
        self._log = {"session_id": session_id, "user_id": user_id}

    def set_jwt(self, jwt_token: str) -> None:
        """
        Replace the service token used for alice-chat-stream.

        The Wyoming path re-mints a short-lived service token per turn so a
        long continued conversation never sends an expired token (PROJ-42
        BUG-2). The WebApp WS path keeps its client-supplied token unchanged.
        """
        self._jwt = jwt_token

    def interrupt(self) -> None:
        """Signal barge-in: stops the LLM stream and discards pending TTS."""
        self._interrupt.set()

    def clear_interrupt(self) -> None:
        self._interrupt.clear()

    async def run_turn(
        self,
        audio: bytes,
        audio_format: str = "webm",
        pcm_rate: int = 16000,
        pcm_width: int = 2,
        pcm_channels: int = 1,
        speak_on_empty: bool = True,
    ) -> PipelineResult:
        """
        Run one full turn: transcribe `audio`, get the AI reply, speak it.

        Returns a PipelineResult. STT/AI/TTS errors produce a spoken German
        error message (except a Piper outage, which raises tts.TTSError).
        """
        # Raw PCM has no container header; ffmpeg/Whisper requires one to detect the format.
        if audio_format == "pcm":
            audio = _pcm_to_wav(audio, rate=pcm_rate, channels=pcm_channels, sampwidth=pcm_width)

        # --- STT ---
        try:
            transcript = await self._stt.transcribe(audio, config.SPEECH_LANGUAGE)
        except STTError:
            await self._speak(config.SPEECH_ERRORS["stt_failed"])
            return PipelineResult()

        if not transcript.strip():
            if speak_on_empty:
                await self._speak(config.SPEECH_ERRORS["stt_empty"])
            return PipelineResult(no_speech=True)

        await self._send_status(STATUS_STT_COMPLETE)
        logger.info("STT transcript: %r", transcript, extra=self._log)

        return await self._run_ai_turn(transcript)

    async def run_text_turn(self, transcript: str) -> PipelineResult:
        """
        Run a turn from an already-transcribed string.

        Used to feed a barge-in interrupt transcript straight back into the
        pipeline as new input without re-running STT.
        """
        return await self._run_ai_turn(transcript)

    async def _run_ai_turn(self, transcript: str) -> PipelineResult:
        self.clear_interrupt()
        await self._send_status(STATUS_AI_PROCESSING)

        accumulator = SentenceAccumulator()
        conversation_ended = False

        # Pipeline parallelism (spec criterion 4.4). Three concurrent stages:
        #   1. LLM token loop (here)  — splits tokens into sentences, queues them
        #   2. Synthesis stage        — pulls sentences, calls Piper, queues audio
        #   3. Send stage             — pulls audio chunks, streams to the client
        # Because synthesis and sending are separate tasks joined by a bounded
        # audio queue, Piper synthesises sentence N+1 while sentence N audio is
        # still being streamed to the client, and the LLM loop never blocks on
        # TTS. The consumer task owns stages 2 and 3.
        sentence_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4)
        consumer = asyncio.create_task(self._tts_consumer(sentence_queue))

        try:
            async for event in stream_reply(
                self.session_id, self.user_id, transcript, self._jwt
            ):
                if self._interrupt.is_set():
                    logger.info("Turn interrupted by barge-in", extra=self._log)
                    break

                if event.kind == "token":
                    for sentence in accumulator.feed(event.text):
                        await sentence_queue.put(sentence)
                elif event.kind == "conversation_end":
                    conversation_ended = True
                elif event.kind == "done":
                    break
        except ChatTimeout:
            await self._drain_consumer(sentence_queue, consumer)
            await self._speak(config.SPEECH_ERRORS["ai_timeout"])
            return PipelineResult()
        except ChatError:
            await self._drain_consumer(sentence_queue, consumer)
            await self._speak(config.SPEECH_ERRORS["ai_failed"])
            return PipelineResult()

        if self._interrupt.is_set():
            await self._drain_consumer(sentence_queue, consumer)
            return PipelineResult(interrupted=True)

        # Flush any trailing partial sentence, then close the queue.
        leftover = accumulator.flush()
        if leftover:
            await sentence_queue.put(leftover)
        await sentence_queue.put(None)  # sentinel — no more sentences

        spoke_anything = await consumer

        if not spoke_anything and not self._interrupt.is_set():
            await self._speak(config.SPEECH_ERRORS["ai_failed"])

        return PipelineResult(conversation_ended=conversation_ended)

    async def _tts_consumer(self, sentence_queue: "asyncio.Queue[str | None]") -> bool:
        """
        Drive the synthesis + send stages for one turn.

        Runs the synthesis stage and the send stage as two concurrent tasks
        joined by a bounded audio queue, so Piper synthesises sentence N+1
        while sentence N audio is still being streamed to the client.

        Returns True if any audio was sent. The `None` sentinel on
        `sentence_queue` ends the turn; barge-in stops both stages early.
        """
        audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=8)
        synth = asyncio.create_task(
            self._synth_stage(sentence_queue, audio_queue)
        )
        sent_any = await self._send_stage(audio_queue)
        synthesised_any = await synth
        return sent_any or synthesised_any

    async def _synth_stage(
        self,
        sentence_queue: "asyncio.Queue[str | None]",
        audio_queue: "asyncio.Queue[bytes | None]",
    ) -> bool:
        """
        Stage 2 — pull sentences, synthesise via Piper, push audio chunks.

        Always pushes the `None` sentinel onto `audio_queue` on exit so the
        send stage terminates even on barge-in or error.
        """
        synthesised_any = False
        try:
            while True:
                sentence = await sentence_queue.get()
                if sentence is None:
                    return synthesised_any
                if self._interrupt.is_set():
                    # Drain remaining sentences without synthesising them.
                    continue
                await self._send_status(STATUS_TTS_GENERATING)
                logger.info("TTS sentence: %r", sentence, extra=self._log)
                async for chunk in tts.synthesize(sentence):
                    if self._interrupt.is_set():
                        break
                    await audio_queue.put(chunk)
                    synthesised_any = True
        finally:
            await audio_queue.put(None)

    async def _send_stage(self, audio_queue: "asyncio.Queue[bytes | None]") -> bool:
        """Stage 3 — pull synthesised audio chunks and stream them to the client."""
        sent_any = False
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                return sent_any
            if self._interrupt.is_set():
                # Discard pending TTS chunks on barge-in; keep draining.
                continue
            await self._send_audio(chunk)
            sent_any = True

    async def _drain_consumer(
        self, queue: "asyncio.Queue[str | None]", consumer: "asyncio.Task[bool]"
    ) -> None:
        """Stop the consumer cleanly after an interrupt or error."""
        await queue.put(None)
        try:
            await consumer
        except Exception:  # noqa: BLE001 — surfaced by the caller's own handling
            logger.debug("TTS consumer ended with error during drain", extra=self._log)

    async def _speak(self, message: str) -> None:
        """Speak a single short message (error / prompt). Re-raises TTSError."""
        async for chunk in tts.synthesize(message):
            await self._send_audio(chunk)
