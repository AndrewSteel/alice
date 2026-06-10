"""
TTS client — synthesises German speech via the existing wyoming-piper
container using the Wyoming client protocol.

One short-lived Wyoming connection is opened per sentence. Sentences are
synthesised concurrently with playback elsewhere in the pipeline, so
sentence 2 is generated while sentence 1 is still playing.

If Piper itself is unavailable this raises TTSError — the caller must then
log and close the connection, since spoken error feedback is impossible
without TTS (see spec: Fehlerbehandlung).
"""
from __future__ import annotations

import audioop  # deprecated in Py3.11, still present in 3.12 — remove if upgrading to 3.13
import logging
from typing import AsyncIterator

from wyoming.audio import AudioChunk, AudioStop
from wyoming.client import AsyncClient
from wyoming.tts import Synthesize

from . import config

logger = logging.getLogger("alice-speech-gateway.tts")

# Gateway delivers 48 kHz 16-bit mono to the HA Voice PE device.
# 48 kHz matches the I2S hardware rate, so the device can use i2s_audio_speaker
# directly without the announcement_resampling_speaker → speaker_mixer chain,
# which has a ~6 s startup delay that causes most audio to be dropped.
_TARGET_RATE = 48000


class TTSError(Exception):
    """Raised when wyoming-piper is unreachable or fails to synthesise."""


async def synthesize(text: str) -> AsyncIterator[bytes]:
    """
    Synthesise one sentence and yield raw PCM audio chunks as they arrive.

    Chunks are yielded incrementally so the caller can stream them straight
    to the client without waiting for the full sentence.
    """
    if not text or not text.strip():
        return

    try:
        resample_state = None
        logged_format = False
        async with AsyncClient.from_uri(config.PIPER_URI) as client:
            await client.write_event(Synthesize(text=text).event())
            while True:
                event = await client.read_event()
                if event is None:
                    break
                if AudioChunk.is_type(event.type):
                    chunk = AudioChunk.from_event(event)
                    if not logged_format:
                        logger.debug(
                            "Piper audio format: rate=%d width=%d channels=%d",
                            chunk.rate, chunk.width, chunk.channels,
                        )
                        logged_format = True
                    audio = chunk.audio
                    if chunk.rate != _TARGET_RATE:
                        audio, resample_state = audioop.ratecv(
                            audio, chunk.width, chunk.channels,
                            chunk.rate, _TARGET_RATE, resample_state,
                        )
                    yield audio
                elif AudioStop.is_type(event.type):
                    break
    except (ConnectionError, OSError) as exc:
        logger.error("wyoming-piper unreachable: %s", exc)
        raise TTSError("TTS nicht erreichbar") from exc
    except Exception as exc:  # noqa: BLE001 — any protocol error is a TTS failure
        logger.error("TTS synthesis failed: %s", exc)
        raise TTSError("TTS fehlgeschlagen") from exc
