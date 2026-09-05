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
from typing import Awaitable, Callable, Optional

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
STATUS_LISTENING = "listening"
STATUS_STT_COMPLETE = "stt_complete"
STATUS_AI_PROCESSING = "ai_processing"
STATUS_TTS_GENERATING = "tts_generating"
STATUS_SESSION_ENDED = "session_ended"


class _ThinkingMessage(str):
    """Waiting message spoken while LLM is still reasoning (PROJ-48).

    Subclasses str so it passes through the TTS pipeline unchanged, but lets
    _synth_stage re-emit ai_processing after speaking it — signalling to the
    UI that Alice is still thinking despite having played audio.
    """


class PipelineResult:
    """Outcome of one utterance turn."""

    __slots__ = (
        "conversation_ended", "interrupted", "no_speech",
        "speaker_user_id", "speaker_confidence", "speaker_display_name",
    )

    def __init__(
        self,
        conversation_ended: bool = False,
        interrupted: bool = False,
        no_speech: bool = False,
        speaker_user_id: Optional[str] = None,
        speaker_confidence: float = 0.0,
        speaker_display_name: Optional[str] = None,
    ) -> None:
        self.conversation_ended = conversation_ended
        self.interrupted = interrupted
        # True when Whisper VAD removed all audio — genuine silence, not a
        # transcription ambiguity. The Wyoming handler uses this to end the
        # session rather than looping back into continued-conversation.
        self.no_speech = no_speech
        # Speaker-ID result for this turn (PROJ-43). None → guest.
        self.speaker_user_id = speaker_user_id
        self.speaker_confidence = speaker_confidence
        self.speaker_display_name = speaker_display_name


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
        tts_target_rate: int | None = None,
        send_audio_format: Callable[[int], Awaitable[None]] | None = None,
        device_id: str | None = None,
        jwt_factory: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self._jwt = jwt_token
        self._stt = stt
        self._send_status = send_status
        self._send_audio = send_audio
        # None → native Piper output (WebApp path, 22 050 Hz).
        # 48 000 → resample for the Wyoming/HA Voice PE I2S speaker.
        self._tts_target_rate = tts_target_rate
        # Optional: called once with Piper's actual sample rate so the client
        # can decode PCM at the correct rate (BUG-5).
        self._send_audio_format = send_audio_format
        self._audio_format_sent = False
        self._interrupt = asyncio.Event()
        self._log = {"session_id": session_id, "user_id": user_id}
        self._device_id = device_id
        # PROJ-43: called with speaker user_id to mint a per-turn service JWT.
        # None → JWT is not updated per turn (WebApp path).
        self._jwt_factory = jwt_factory

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
        speaker_profiles: Optional[list] = None,
        is_first_turn: bool = False,
    ) -> PipelineResult:
        """
        Run one full turn: transcribe `audio`, get the AI reply, speak it.

        PROJ-43: when speaker_profiles is provided, Speaker-ID runs in parallel
        with STT. The identified user's JWT replaces the session token for this
        turn so alice-chat-stream uses the correct user context.

        Returns a PipelineResult. STT/AI/TTS errors produce a spoken German
        error message (except a Piper outage, which raises tts.TTSError).
        """
        # Raw PCM has no container header; ffmpeg/Whisper requires one to detect the format.
        if audio_format == "pcm":
            audio = _pcm_to_wav(audio, rate=pcm_rate, channels=pcm_channels, sampwidth=pcm_width)

        # --- STT + Speaker-ID in parallel (PROJ-43) ---
        stt_task = asyncio.create_task(self._stt.transcribe(audio, config.SPEECH_LANGUAGE))

        speaker_task: Optional[asyncio.Task] = None
        if speaker_profiles is not None:
            from . import speaker_id as _sid
            if _sid.is_ready():
                speaker_task = asyncio.create_task(
                    _sid.identify_from_audio(audio, speaker_profiles, config.SPEAKER_THRESHOLD)
                )

        try:
            transcript = await stt_task
        except STTError:
            if speaker_task:
                speaker_task.cancel()
            await self._speak(config.SPEECH_ERRORS["stt_failed"])
            return PipelineResult()

        # Collect Speaker-ID result (2 s budget; fall back to guest on timeout)
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

        # Update JWT and user_id for this turn if the speaker was identified
        if spk_user_id and self._jwt_factory:
            self._jwt = self._jwt_factory(spk_user_id)
            self.user_id = spk_user_id
            self._log = {"session_id": self.session_id, "user_id": self.user_id}

        if not transcript.strip():
            if speak_on_empty:
                await self._speak(config.SPEECH_ERRORS["stt_empty"])
            return PipelineResult(
                no_speech=True,
                speaker_user_id=spk_user_id,
                speaker_confidence=spk_confidence,
                speaker_display_name=spk_display_name,
            )

        await self._send_status(STATUS_STT_COMPLETE)
        logger.info(
            "STT transcript: %r  speaker=%r (conf=%.2f)",
            transcript, spk_user_id, spk_confidence,
            extra=self._log,
        )

        # Determine first-turn greeting (PROJ-43)
        greeting: Optional[str] = None
        if is_first_turn:
            if spk_display_name:
                greeting = f"Hallo {spk_display_name},"
            else:
                greeting = "Hallo Gast,"

        result = await self._run_ai_turn(transcript, greeting=greeting)
        result.speaker_user_id = spk_user_id
        result.speaker_confidence = spk_confidence
        result.speaker_display_name = spk_display_name
        return result

    async def run_text_turn(
        self,
        transcript: str,
        speaker_user_id: Optional[str] = None,
        speaker_confidence: float = 0.0,
        speaker_display_name: Optional[str] = None,
        is_first_turn: bool = False,
    ) -> PipelineResult:
        """
        Run a turn from an already-transcribed string.

        Used when the caller has already run STT (Wyoming handler) or when
        feeding a barge-in interrupt transcript back without re-running STT.

        PROJ-43: if speaker_user_id is provided, the pipeline JWT is updated
        before the alice-chat-stream call.
        """
        if speaker_user_id and self._jwt_factory:
            self._jwt = self._jwt_factory(speaker_user_id)
            self.user_id = speaker_user_id
            self._log = {"session_id": self.session_id, "user_id": self.user_id}

        greeting: Optional[str] = None
        if is_first_turn:
            if speaker_display_name:
                greeting = f"Hallo {speaker_display_name},"
            else:
                greeting = "Hallo Gast,"

        result = await self._run_ai_turn(transcript, greeting=greeting)
        result.speaker_user_id = speaker_user_id
        result.speaker_confidence = speaker_confidence
        result.speaker_display_name = speaker_display_name
        return result

    async def _run_ai_turn(
        self,
        transcript: str,
        greeting: Optional[str] = None,
    ) -> PipelineResult:
        """
        Drive the LLM → TTS pipeline for one turn.

        greeting (PROJ-43): "Hallo {name}," or "Hallo Gast," on the first turn
        of a session. Injected differently per session type:
          - llm  path: replaces the "Warte bitte" waiting message when
                       thinking_start fires.
          - ha_only path: prepended to the first sentence's text (no LLM
                           reasoning, so thinking_start never fires).
        """
        self.clear_interrupt()
        await self._send_status(STATUS_AI_PROCESSING)

        accumulator = SentenceAccumulator()
        conversation_ended = False
        greeting_pending = greeting  # consumed on the first relevant event

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
                self.session_id, self.user_id, transcript, self._jwt,
                device_id=self._device_id,
            ):
                if self._interrupt.is_set():
                    logger.info("Turn interrupted by barge-in", extra=self._log)
                    break

                if event.kind == "path":
                    # PROJ-83 ZUSATZ: on the HA_FAST path the personal greeting
                    # ("Hallo Andreas,") sounds intrusive in front of a short
                    # confirmation — drop it. The identified speaker is still
                    # used for permissions and recorded in the chat history by
                    # alice-chat-stream; it is just not spoken. The greeting
                    # stays on the LLM path (its purpose there is to signal who
                    # was recognised before a longer answer).
                    if event.text == "HA_FAST":
                        greeting_pending = None
                elif event.kind == "token":
                    if greeting_pending:
                        # llm path with no reasoning block (no thinking_start):
                        # prepend the greeting to the first sentence.
                        accumulator.feed(greeting_pending + " ")
                        greeting_pending = None
                    for sentence in accumulator.feed(event.text):
                        await sentence_queue.put(sentence)
                elif event.kind == "thinking_start":
                    if not self._interrupt.is_set():
                        if greeting_pending:
                            # llm path: use greeting as the waiting message
                            name = greeting_pending.rstrip(",").replace("Hallo ", "")
                            if name == "Gast":
                                msg = config.SPEECH_GREETING_THINKING["guest"]
                            else:
                                msg = config.SPEECH_GREETING_THINKING["known"].format(name=name)
                            await sentence_queue.put(_ThinkingMessage(msg))
                            greeting_pending = None
                        else:
                            waiting_msg = config.SPEECH_THINKING.get(
                                event.text, config.SPEECH_THINKING["du"]
                            )
                            await sentence_queue.put(_ThinkingMessage(waiting_msg))
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
                is_thinking_msg = isinstance(sentence, _ThinkingMessage)
                await self._send_status(STATUS_TTS_GENERATING)
                logger.info("TTS sentence: %r", sentence, extra=self._log)
                # BUG-5: announce Piper's actual sample rate on the first chunk
                # of the session so the client can decode PCM at the right rate.
                on_rate = None
                if not self._audio_format_sent and self._send_audio_format is not None:
                    async def _on_rate(rate: int) -> None:
                        self._audio_format_sent = True
                        await self._send_audio_format(rate)  # type: ignore[misc]
                    on_rate = _on_rate
                async for chunk in tts.synthesize(
                    sentence, target_rate=self._tts_target_rate, on_first_rate=on_rate
                ):
                    if self._interrupt.is_set():
                        break
                    await audio_queue.put(chunk)
                    synthesised_any = True
                # After speaking the waiting message, signal that the LLM is
                # still reasoning so the UI returns to "Alice denkt…".
                if is_thinking_msg and not self._interrupt.is_set():
                    await self._send_status(STATUS_AI_PROCESSING)
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
        async for chunk in tts.synthesize(message, target_rate=self._tts_target_rate):
            await self._send_audio(chunk)
