"""
Barge-in controller — 3-stage filter that decides whether incoming audio
during TTS playback should interrupt the running pipeline.

  Stage 1  VAD pre-filter      — webrtcvad; rejects silence/noise (CPU, fast)
  Stage 2  Background STT      — faster-whisper on speech-like segments
  Stage 3  Intent classifier   — rule-based match against interrupt phrases
  Stage 4  [PROJ-43 hook]      — speaker verification; disabled until PROJ-43

Only a stage-3 match triggers an interrupt. TV / radio / side conversation
that VAD or Whisper picks up but that contains no interrupt phrase is
silently discarded — the running pipeline continues.
"""
from __future__ import annotations

import logging
import re

from . import config
from .stt import STTEngine

logger = logging.getLogger("alice-speech-gateway.barge_in")

# webrtcvad requires 16-bit mono PCM at 8/16/32 kHz, frames of 10/20/30 ms.
_VAD_SAMPLE_RATE = 16000
_VAD_FRAME_MS = 30
_VAD_FRAME_BYTES = int(_VAD_SAMPLE_RATE * (_VAD_FRAME_MS / 1000.0) * 2)
# Fraction of frames that must be voiced for a segment to be "speech-like".
_VAD_SPEECH_RATIO = 0.4


class VADPreFilter:
    """Stage 1 — lightweight voice-activity detection on raw PCM."""

    def __init__(self, aggressiveness: int = 2) -> None:
        # Import here so the module imports without webrtcvad installed.
        import webrtcvad

        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech_like(self, pcm: bytes) -> bool:
        """True if a meaningful fraction of 16 kHz PCM frames are voiced."""
        if len(pcm) < _VAD_FRAME_BYTES:
            return False
        voiced = 0
        total = 0
        for off in range(0, len(pcm) - _VAD_FRAME_BYTES + 1, _VAD_FRAME_BYTES):
            frame = pcm[off: off + _VAD_FRAME_BYTES]
            total += 1
            try:
                if self._vad.is_speech(frame, _VAD_SAMPLE_RATE):
                    voiced += 1
            except Exception:  # noqa: BLE001 — bad frame, treat as non-voiced
                continue
        return total > 0 and (voiced / total) >= _VAD_SPEECH_RATIO


class IntentClassifier:
    """Stage 3 — rule-based interrupt-phrase matcher (MVP)."""

    def __init__(self, phrases: list[str]) -> None:
        # Whole-word, case-insensitive substring match per phrase.
        self._patterns = [
            re.compile(r"\b" + re.escape(p.lower()) + r"\b") for p in phrases
        ]

    def is_interrupt(self, transcript: str) -> bool:
        if not transcript or not transcript.strip():
            return False
        text = transcript.lower()
        return any(p.search(text) for p in self._patterns)


class BargeInController:
    """Runs all stages and returns the interrupt transcript, or None."""

    def __init__(self, stt: STTEngine, phrases: list[str] | None = None) -> None:
        self._stt = stt
        self._vad = VADPreFilter()
        self._classifier = IntentClassifier(
            phrases if phrases is not None else config.load_interrupt_phrases()
        )

    async def evaluate(
        self,
        pcm: bytes,
        webm: bytes | None = None,
        speaker_ok: bool = True,
    ) -> str | None:
        """
        Decide whether `pcm` (16 kHz mono) should interrupt the pipeline.

        Returns the interrupt transcript on a match, else None.

        `webm` is the same audio in a Whisper-decodable container if the
        client sends one; otherwise `pcm` is transcribed directly.
        `speaker_ok` is the PROJ-43 hook — defaults True (disabled) until
        speaker verification is integrated.
        """
        # Stage 1 — VAD pre-filter: drop obvious silence/noise without Whisper.
        if not self._vad.is_speech_like(pcm):
            return None

        # Stage 2 — STT on the speech-like segment.
        audio_for_stt = webm if webm is not None else pcm
        try:
            transcript = await self._stt.transcribe(audio_for_stt)
        except Exception as exc:  # noqa: BLE001 — STT failure: no interrupt
            logger.warning("Barge-in STT failed, ignoring segment: %s", exc)
            return None
        if not transcript.strip():
            # VAD false positive — empty transcript, no interrupt.
            return None

        # Stage 3 — intent classification: only interrupt phrases count.
        if not self._classifier.is_interrupt(transcript):
            logger.debug("Barge-in transcript has no interrupt intent: %r", transcript)
            return None

        # Stage 4 — [PROJ-43 hook] speaker verification (disabled by default).
        if not speaker_ok:
            logger.debug("Barge-in rejected: speaker mismatch")
            return None

        logger.info("Barge-in interrupt detected: %r", transcript)
        return transcript
