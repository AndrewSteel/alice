"""
audio_decode.py — streaming webm/opus → PCM decoder for the barge-in path.

PROJ-41's WebApp client uses `MediaRecorder` (webm/opus container) per the
PROJ-40 client-format contract. The barge-in VAD stage (`webrtcvad`) requires
raw 16 kHz mono 16-bit PCM, and Whisper needs a self-contained, decodable
audio segment. Individual `MediaRecorder` chunks after the first are *not*
self-contained — only the first chunk carries the EBML/Init headers — so
chunks cannot be decoded one-by-one.

Solution: one persistent ffmpeg subprocess per voice session. The receiver
feeds every incoming webm chunk to ffmpeg's stdin; a background task drains
ffmpeg's stdout into a PCM buffer that the barge-in evaluator consumes.
"""
from __future__ import annotations

import asyncio
import logging
import struct

logger = logging.getLogger("alice-speech-gateway.audio_decode")

# 16 kHz / mono / s16le — matches the barge-in VAD frame format.
_TARGET_SAMPLE_RATE = 16000


def pcm_to_wav(pcm: bytes, sample_rate: int = _TARGET_SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit signed mono PCM in a minimal WAV container.

    Whisper auto-detects the input format via ffmpeg; a WAV header is the
    cheapest way to make a raw-PCM buffer Whisper-decodable.
    """
    channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm)
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack(
            "<IHHIIHH",
            16,                # PCM chunk size
            1,                 # PCM format
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
        )
        + b"data"
        + struct.pack("<I", data_size)
        + pcm
    )


class WebmPcmDecoder:
    """Persistent ffmpeg-backed webm/opus → PCM stream decoder (one per session).

    Usage:
        decoder = WebmPcmDecoder()
        await decoder.start()
        ...
        await decoder.feed(webm_chunk)        # on every incoming WS audio frame
        pcm = decoder.take_pcm()              # consume buffered PCM
        ...
        await decoder.close()                 # on session teardown
    """

    def __init__(self, sample_rate: int = _TARGET_SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._pcm_buffer = bytearray()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-loglevel", "quiet",
            "-i", "pipe:0",
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", str(self._sample_rate),
            "-ac", "1",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._reader_task = asyncio.create_task(self._drain_stdout())

    async def _drain_stdout(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                chunk = await self._proc.stdout.read(4096)
                if not chunk:
                    return
                self._pcm_buffer.extend(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — log and stop draining
            logger.warning("PCM reader error: %s", exc)

    async def feed(self, webm_chunk: bytes) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        if self._proc.stdin.is_closing():
            return
        try:
            self._proc.stdin.write(webm_chunk)
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            # ffmpeg died — stop accepting further feed() calls.
            self._proc = None

    def take_pcm(self) -> bytes:
        """Return all PCM produced since the last call and clear the buffer."""
        data = bytes(self._pcm_buffer)
        self._pcm_buffer.clear()
        return data

    def discard_pcm(self) -> None:
        self._pcm_buffer.clear()

    async def close(self) -> None:
        if self._proc is None and self._reader_task is None:
            return
        proc = self._proc
        self._proc = None
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reader_task = None
        if proc is not None:
            try:
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:  # noqa: BLE001
                    pass
        self._pcm_buffer.clear()
