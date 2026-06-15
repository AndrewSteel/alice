"""
Integration tests for the /ws/voice transport loop (BUG-1 / BUG-3).

These exercise `_voice_loop` directly with a fake WebSocket, a fake
VoicePipeline and a fake BargeInController, so they run without a GPU,
without alice-chat-stream and without Piper. They verify the wiring that
the QA pass found missing:

  - audio received DURING a running turn is routed to barge-in evaluation
  - a barge-in match interrupts the running pipeline and feeds the
    interrupt transcript back in as a new turn (same session)
  - non-interrupt audio is discarded and the pipeline turn completes
  - silence timeout / stop / conversation_end still end the session
  - a TTSError aborts the session cleanly instead of crashing the handler
"""
import asyncio
import json

import pytest

from app import config, stt, ws_transport
from app.pipeline import PipelineResult
from app.stt import STTError
from app.tts import TTSError


class FakeWebSocket:
    """
    Minimal WebSocket double.

    `script` is a list of frames the client "sends"; each is one of:
      {"bytes": b"..."}                      — binary audio frame
      {"text": '{"type": "end_of_utterance"}'} — JSON control frame
      {"type": "websocket.disconnect"}        — client disconnect
      {"sleep": 0.01}                         — yield to the event loop
    Frames are delivered in order; once exhausted, `receive()` blocks
    forever (so a silence-timeout path can be tested with a short timeout).
    """

    def __init__(self, script):
        self._script = list(script)
        self.sent_json = []
        self.sent_bytes = []
        self.closed = None

    async def receive(self):
        while self._script:
            frame = self._script.pop(0)
            if "sleep" in frame:
                await asyncio.sleep(frame["sleep"])
                continue
            return frame
        # Nothing left — block (lets asyncio.wait_for hit the timeout).
        await asyncio.Event().wait()

    async def send_json(self, data):
        self.sent_json.append(data)

    async def send_bytes(self, data):
        self.sent_bytes.append(data)

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


class FakePipeline:
    """Records turns; lets a test script the PipelineResult per turn."""

    def __init__(self, results):
        self._results = list(results)
        self.audio_turns = []
        self.text_turns = []
        self.interrupted = False
        self._interrupt_event = asyncio.Event()

    def interrupt(self):
        self.interrupted = True
        self._interrupt_event.set()

    async def run_turn(self, audio, audio_format="webm"):
        self.audio_turns.append(audio)
        return await self._next_result()

    async def run_text_turn(self, transcript):
        self.text_turns.append(transcript)
        return await self._next_result()

    async def _next_result(self):
        # Give the receiver task a chance to run (barge-in during the turn).
        await asyncio.sleep(0.02)
        if self._results:
            return self._results.pop(0)
        return PipelineResult()

    async def _speak(self, message):
        pass


class FakeBargeIn:
    """Returns a scripted transcript (or None) for each `evaluate` call."""

    def __init__(self, transcripts):
        self._transcripts = list(transcripts)
        self.calls = 0

    async def evaluate(self, pcm, webm=None, speaker_ok=True):
        self.calls += 1
        if self._transcripts:
            return self._transcripts.pop(0)
        return None


_PCM_BYTES_PER_SEC = 16000 * 2  # 16 kHz mono 16-bit


def _audio(seconds: float) -> bytes:
    """Bytes representing `seconds` of 16 kHz mono 16-bit PCM."""
    return b"\x00" * int(_PCM_BYTES_PER_SEC * seconds)


class FakeDecoder:
    """
    Stand-in for `WebmPcmDecoder` in tests — bypasses ffmpeg.

    The receiver feeds it webm chunks; we just echo them back as if they
    were already PCM so the barge-in path sees enough bytes to evaluate.
    """

    def __init__(self):
        self._buf = bytearray()

    async def feed(self, chunk):
        self._buf.extend(chunk)

    def take_pcm(self):
        data = bytes(self._buf)
        self._buf.clear()
        return data

    def discard_pcm(self):
        self._buf.clear()

    async def close(self):
        pass


async def test_normal_turn_then_conversation_end(monkeypatch):
    """
    conversation_ended is ignored in the WebApp voice path — the session stays
    open after HA commands and ends only via silence timeout.
    """
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.5)
    pipeline = FakePipeline([PipelineResult(conversation_ended=True)])
    barge_in = FakeBargeIn([])
    ws = FakeWebSocket([
        {"bytes": _audio(1.0)},
        {"text": json.dumps({"type": "end_of_utterance"})},
    ])

    await ws_transport._voice_loop(ws, pipeline, barge_in, {}, decoder=FakeDecoder())

    assert len(pipeline.audio_turns) == 1
    assert pipeline.text_turns == []
    assert ws.closed == (1000, "session ended")


async def test_barge_in_interrupts_running_turn(monkeypatch):
    """
    BUG-1 regression: audio arriving while a turn runs is evaluated for
    barge-in; a non-stop-word match interrupts the pipeline and the
    interrupt transcript is fed back as a new (text) turn.
    """
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.5)
    # First (audio) turn returns interrupted=True because barge-in fired;
    # the follow-up text turn completes the conversation.
    pipeline = FakePipeline([
        PipelineResult(interrupted=True),
        PipelineResult(conversation_ended=True),
    ])
    # Use a non-stop-word transcript so it is fed back to the LLM.
    barge_in = FakeBargeIn(["Wechsle das Thema"])
    ws = FakeWebSocket([
        {"bytes": _audio(1.0)},
        {"text": json.dumps({"type": "end_of_utterance"})},
        # Audio that arrives WHILE the first turn is running -> barge-in path.
        {"sleep": 0.005},
        {"bytes": _audio(1.0)},
    ])

    await ws_transport._voice_loop(ws, pipeline, barge_in, {}, decoder=FakeDecoder())

    assert pipeline.interrupted is True
    assert barge_in.calls >= 1
    # The interrupt transcript was fed back in as a new turn.
    assert pipeline.text_turns == ["Wechsle das Thema"]
    assert ws.closed == (1000, "session ended")


async def test_barge_in_stop_only_does_not_feed_llm(monkeypatch):
    """
    A pure stop-word barge-in ("stop", "warte" etc.) must abort the turn
    without sending the control word to the LLM. Feeding "stop" to the
    LLM caused unintended HA commands (e.g., deactivating devices).
    """
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.5)
    pipeline = FakePipeline([PipelineResult(interrupted=True)])
    barge_in = FakeBargeIn(["stop"])
    ws = FakeWebSocket([
        {"bytes": _audio(1.0)},
        {"text": json.dumps({"type": "end_of_utterance"})},
        {"sleep": 0.005},
        {"bytes": _audio(1.0)},
    ])

    await ws_transport._voice_loop(ws, pipeline, barge_in, {}, decoder=FakeDecoder())

    assert pipeline.interrupted is True
    # "stop" must NOT be fed to the LLM as a new turn.
    assert pipeline.text_turns == []
    assert ws.closed == (1000, "session ended")


async def test_non_interrupt_audio_is_discarded(monkeypatch):
    """
    Audio during a turn that has no interrupt intent (TV/radio) is
    discarded; the pipeline turn finishes normally.
    """
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.5)
    pipeline = FakePipeline([PipelineResult(conversation_ended=True)])
    barge_in = FakeBargeIn([None])  # evaluate -> no interrupt
    ws = FakeWebSocket([
        {"bytes": _audio(1.0)},
        {"text": json.dumps({"type": "end_of_utterance"})},
        {"sleep": 0.005},
        {"bytes": _audio(1.0)},  # background noise during the turn
    ])

    await ws_transport._voice_loop(ws, pipeline, barge_in, {}, decoder=FakeDecoder())

    assert pipeline.interrupted is False
    assert pipeline.text_turns == []
    assert ws.closed == (1000, "session ended")


async def test_silence_timeout_ends_session(monkeypatch):
    """No frames at all -> silence timeout closes the session."""
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.05)
    pipeline = FakePipeline([])
    barge_in = FakeBargeIn([])
    ws = FakeWebSocket([])  # client sends nothing

    await ws_transport._voice_loop(ws, pipeline, barge_in, {}, decoder=FakeDecoder())

    assert pipeline.audio_turns == []
    assert ws.closed == (1000, "session ended")


async def test_stop_frame_ends_session(monkeypatch):
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.5)
    pipeline = FakePipeline([])
    barge_in = FakeBargeIn([])
    ws = FakeWebSocket([{"text": json.dumps({"type": "stop"})}])

    await ws_transport._voice_loop(ws, pipeline, barge_in, {}, decoder=FakeDecoder())

    assert ws.closed == (1000, "session ended")


async def test_client_disconnect_ends_loop(monkeypatch):
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.5)
    pipeline = FakePipeline([])
    barge_in = FakeBargeIn([])
    ws = FakeWebSocket([{"type": "websocket.disconnect"}])

    await ws_transport._voice_loop(ws, pipeline, barge_in, {}, decoder=FakeDecoder())

    # _CLOSED path returns without sending a session-ended status.
    assert ws.closed is None


async def test_ttserror_aborts_session_cleanly(monkeypatch):
    """
    BUG-5 regression: a Piper outage (TTSError) inside a turn must not
    crash the handler — `ws_voice` catches it, logs, and closes the socket.
    """
    monkeypatch.setattr(config, "SILENCE_TIMEOUT_SECONDS", 0.5)

    class ExplodingPipeline(FakePipeline):
        async def run_turn(self, audio, audio_format="webm"):
            raise TTSError("Piper down")

    pipeline = ExplodingPipeline([])
    barge_in = FakeBargeIn([])
    ws = FakeWebSocket([
        {"bytes": _audio(1.0)},
        {"text": json.dumps({"type": "end_of_utterance"})},
    ])

    # _voice_loop lets TTSError propagate; ws_voice catches it. Mirror that
    # contract here: the loop raises, the handler-level except handles it.
    with pytest.raises(TTSError):
        await ws_transport._voice_loop(ws, pipeline, barge_in, {}, decoder=FakeDecoder())


# --- Mode 1 streaming STT (/ws/stt) ---------------------------------------


class FakeSTT:
    """Scripted STT engine: returns the next transcript (or raises) per call."""

    def __init__(self, transcripts):
        self._transcripts = list(transcripts)
        self.calls = 0

    async def transcribe(self, audio, language=None):
        self.calls += 1
        if not self._transcripts:
            return ""
        item = self._transcripts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def test_stt_streaming_interim_then_final(monkeypatch):
    """
    Streaming Mode 1: a rolling interim is emitted while recording, then a
    single authoritative final on end_of_utterance, then the socket closes.
    """
    # Interval 0 → the first chunk triggers an interim transcription.
    monkeypatch.setattr(ws_transport, "_STT_INTERIM_INTERVAL_S", 0.0)
    monkeypatch.setattr(stt, "_engine", FakeSTT(["Hallo", "Hallo Alice"]))
    ws = FakeWebSocket([
        {"bytes": _audio(0.25)},
        {"sleep": 0.01},  # let the interim task run
        {"text": json.dumps({"type": "end_of_utterance"})},
    ])

    await ws_transport._stt_loop(ws, {})

    assert ws.sent_json == [
        {"type": "interim", "text": "Hallo"},
        {"type": "final", "text": "Hallo Alice"},
    ]
    assert ws.closed == (1000, "")


async def test_stt_streaming_final_only_when_under_interval(monkeypatch):
    """Chunks within the interim interval produce no interim — only the final."""
    # Default 2 s interval; chunks arrive instantly, so no interim fires.
    monkeypatch.setattr(stt, "_engine", FakeSTT(["Hallo Alice"]))
    ws = FakeWebSocket([
        {"bytes": _audio(0.25)},
        {"bytes": _audio(0.25)},
        {"text": json.dumps({"type": "end_of_utterance"})},
    ])

    await ws_transport._stt_loop(ws, {})

    assert ws.sent_json == [{"type": "final", "text": "Hallo Alice"}]
    assert ws.closed == (1000, "")


async def test_stt_streaming_empty_final(monkeypatch):
    """An empty final is sent as-is (the client shows 'Nichts verstanden')."""
    monkeypatch.setattr(stt, "_engine", FakeSTT([""]))
    ws = FakeWebSocket([
        {"bytes": _audio(0.25)},
        {"text": json.dumps({"type": "end_of_utterance"})},
    ])

    await ws_transport._stt_loop(ws, {})

    assert ws.sent_json == [{"type": "final", "text": ""}]
    assert ws.closed == (1000, "")


async def test_stt_streaming_final_failure_sends_error(monkeypatch):
    """An STTError on the final transcription surfaces as an error frame."""
    monkeypatch.setattr(stt, "_engine", FakeSTT([STTError("boom")]))
    ws = FakeWebSocket([
        {"bytes": _audio(0.25)},
        {"text": json.dumps({"type": "end_of_utterance"})},
    ])

    await ws_transport._stt_loop(ws, {})

    assert ws.sent_json == [
        {"type": "error", "message": config.SPEECH_ERRORS["stt_failed"]}
    ]
    assert ws.closed == (1000, "")


async def test_stt_streaming_disconnect_before_final(monkeypatch):
    """A client disconnect mid-stream ends the loop without a final or close."""
    monkeypatch.setattr(stt, "_engine", FakeSTT(["Hallo"]))
    ws = FakeWebSocket([
        {"bytes": _audio(0.25)},
        {"type": "websocket.disconnect"},
    ])

    await ws_transport._stt_loop(ws, {})

    assert ws.sent_json == []
    assert ws.closed is None
