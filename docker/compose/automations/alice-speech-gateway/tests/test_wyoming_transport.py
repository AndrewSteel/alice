"""
Integration tests for the Wyoming transport continued conversation (BUG-4).

These exercise GatewayWyomingHandler directly without a real Wyoming TCP
server, a GPU, alice-chat-stream, or Piper. VoicePipeline, get_engine, and
_service_token_for are all monkeypatched.

Covered:
  - _collect_audio collects a full AudioStart/AudioChunk/AudioStop block
  - _collect_audio returns None on silence timeout
  - conversation continues for a second turn after the first completes
  - conversation_end signal from the pipeline ends the session after one turn
  - silence timeout between turns ends the session
  - unknown device-id gets a spoken error (pre-existing behaviour preserved)
"""
from __future__ import annotations

import asyncio

import pytest
from wyoming.audio import AudioChunk, AudioStart, AudioStop

from app import config
from app.pipeline import PipelineResult
from app.wyoming_transport import GatewayWyomingHandler

_RATE = 16000
_WIDTH = 2
_CHANNELS = 1


def _pcm(seconds: float) -> bytes:
    return b"\x00" * int(_RATE * _WIDTH * seconds)


def _audio_start() -> object:
    return AudioStart(rate=_RATE, width=_WIDTH, channels=_CHANNELS).event()


def _audio_chunk(seconds: float) -> object:
    return AudioChunk(rate=_RATE, width=_WIDTH, channels=_CHANNELS, audio=_pcm(seconds)).event()


def _audio_stop() -> object:
    return AudioStop().event()


class FakePipeline:
    def __init__(self, results):
        self._results = list(results)
        self.turns: list[bytes] = []

    async def run_turn(self, audio: bytes, audio_format: str = "pcm") -> PipelineResult:
        self.turns.append(audio)
        await asyncio.sleep(0)  # yield to let other tasks run
        return self._results.pop(0) if self._results else PipelineResult()


class _TestableHandler(GatewayWyomingHandler):
    """
    Subclass that bypasses AsyncEventHandler.__init__ (which needs a real TCP
    reader/writer) and captures every write_event call.
    """

    def __init__(self, device_mapping: dict[str, int], device_id: str = "test-device"):
        # Directly initialise our own attributes only.
        self._device_mapping = device_mapping
        self._info = None
        self._device_id = device_id
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._loop_task = None
        self.written_events: list = []

    async def write_event(self, event) -> None:
        self.written_events.append(event)


async def _feed_block(handler: _TestableHandler, seconds: float) -> None:
    """Feed one AudioStart/AudioChunk/AudioStop triple into the handler."""
    await handler.handle_event(_audio_start())
    await handler.handle_event(_audio_chunk(seconds))
    await handler.handle_event(_audio_stop())


def _written_types(handler: _TestableHandler) -> list[str]:
    return [e.type for e in handler.written_events]


# ---------------------------------------------------------------------------
# _collect_audio unit tests (no pipeline involved)
# ---------------------------------------------------------------------------

async def test_collect_audio_returns_pcm(monkeypatch):
    """_collect_audio returns the accumulated PCM for a complete block."""
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 1.0)
    handler = _TestableHandler({})

    pcm = _pcm(0.5)
    handler._event_queue.put_nowait(_audio_start())
    handler._event_queue.put_nowait(
        AudioChunk(rate=_RATE, width=_WIDTH, channels=_CHANNELS, audio=pcm).event()
    )
    handler._event_queue.put_nowait(_audio_stop())

    result = await handler._collect_audio()
    assert result == pcm


async def test_collect_audio_timeout(monkeypatch):
    """_collect_audio returns None when the silence timeout fires."""
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.05)
    handler = _TestableHandler({})

    result = await handler._collect_audio()
    assert result is None


# ---------------------------------------------------------------------------
# Continued conversation tests (pipeline monkeypatched)
# ---------------------------------------------------------------------------

async def test_continued_conversation_two_turns(monkeypatch):
    """
    BUG-4 regression: after the first turn, the session stays open and
    processes a second utterance using the same pipeline (same session_id).
    """
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 1.0)
    fake = FakePipeline([PipelineResult(), PipelineResult(conversation_ended=True)])
    monkeypatch.setattr("app.wyoming_transport.VoicePipeline",
                        lambda **kw: fake)
    monkeypatch.setattr("app.wyoming_transport._service_token_for", lambda uid: "tok")
    monkeypatch.setattr("app.wyoming_transport.get_engine", lambda: None)

    handler = _TestableHandler({"test-device": 1})

    # Feed both utterances before awaiting the task (they queue up).
    await _feed_block(handler, 1.0)
    await _feed_block(handler, 1.0)

    assert handler._loop_task is not None
    await handler._loop_task

    assert len(fake.turns) == 2
    # Two audio-start/audio-stop pairs written back for the two TTS responses.
    types = _written_types(handler)
    assert types.count("audio-start") == 2
    assert types.count("audio-stop") == 2


async def test_conversation_ended_signal_stops_after_one_turn(monkeypatch):
    """A conversation_end result ends the session without waiting for more audio."""
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 1.0)
    fake = FakePipeline([PipelineResult(conversation_ended=True)])
    monkeypatch.setattr("app.wyoming_transport.VoicePipeline", lambda **kw: fake)
    monkeypatch.setattr("app.wyoming_transport._service_token_for", lambda uid: "tok")
    monkeypatch.setattr("app.wyoming_transport.get_engine", lambda: None)

    handler = _TestableHandler({"test-device": 1})
    await _feed_block(handler, 1.0)

    assert handler._loop_task is not None
    await handler._loop_task

    assert len(fake.turns) == 1


async def test_silence_timeout_between_turns_ends_session(monkeypatch):
    """Silence timeout after the first turn ends the session cleanly."""
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.05)
    fake = FakePipeline([PipelineResult()])  # first turn: no conversation_end
    monkeypatch.setattr("app.wyoming_transport.VoicePipeline", lambda **kw: fake)
    monkeypatch.setattr("app.wyoming_transport._service_token_for", lambda uid: "tok")
    monkeypatch.setattr("app.wyoming_transport.get_engine", lambda: None)

    handler = _TestableHandler({"test-device": 1})
    await _feed_block(handler, 1.0)

    assert handler._loop_task is not None
    await handler._loop_task  # loop exits on silence timeout after turn 1

    assert len(fake.turns) == 1


async def test_unknown_device_gets_spoken_error(monkeypatch):
    """
    Pre-existing behaviour: unknown device-id produces a spoken error and
    the loop then times out (no pipeline turn runs).
    """
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.05)
    spoken: list[str] = []

    async def fake_speak_error(self, message: str):
        spoken.append(message)

    monkeypatch.setattr(_TestableHandler, "_speak_error", fake_speak_error)

    handler = _TestableHandler(device_mapping={}, device_id="unknown-device")
    await _feed_block(handler, 1.0)

    assert handler._loop_task is not None
    await handler._loop_task

    assert spoken == [config.SPEECH_ERRORS["unknown_device"]]
