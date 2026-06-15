"""
Tests for VoicePipeline orchestration.

The STT engine, chat client and TTS synthesiser are all faked, so these
tests run without a GPU, without alice-chat-stream and without Piper.
They verify: STT->AI->TTS happy path, sentence-streamed TTS, empty-STT
spoken error, AI-timeout spoken error, and barge-in cancellation.
"""
import asyncio

import pytest

from app import chat_client, pipeline, tts
from app.chat_client import ChatEvent
from app.stt import STTEngine


class FakeSTT(STTEngine):
    def __init__(self, transcript: str):
        self._transcript = transcript

    async def transcribe(self, audio: bytes, language=None) -> str:
        return self._transcript


@pytest.fixture
def captured():
    return {"status": [], "audio": []}


@pytest.fixture
def make_pipeline(captured, monkeypatch):
    """Factory: build a VoicePipeline with capturing callbacks + fake TTS."""

    async def _fake_synthesize(text: str, target_rate=None, on_first_rate=None):
        if on_first_rate is not None:
            await on_first_rate(22050)
        # One audio chunk per sentence — lets tests count spoken sentences.
        yield f"AUDIO[{text}]".encode()

    monkeypatch.setattr(tts, "synthesize", _fake_synthesize)

    async def send_status(s):
        captured["status"].append(s)

    async def send_audio(b):
        captured["audio"].append(b)

    def _factory(stt):
        return pipeline.VoicePipeline(
            session_id="sess-1",
            user_id="7",
            jwt_token="tok",
            stt=stt,
            send_status=send_status,
            send_audio=send_audio,
        )

    return _factory


def _fake_stream(events):
    async def _gen(*_args, **_kwargs):
        for e in events:
            yield e

    return _gen


async def test_happy_path_streams_sentences(make_pipeline, captured, monkeypatch):
    monkeypatch.setattr(
        chat_client,
        "stream_reply",
        _fake_stream([
            ChatEvent("token", "Hallo. "),
            ChatEvent("token", "Wie geht es dir?"),
            ChatEvent("done"),
        ]),
    )
    monkeypatch.setattr(pipeline, "stream_reply", chat_client.stream_reply)

    p = make_pipeline(FakeSTT("Guten Tag"))
    result = await p.run_turn(b"x" * 100000)

    assert not result.conversation_ended
    assert not result.interrupted
    # Two sentences -> two TTS audio chunks.
    assert captured["audio"] == [b"AUDIO[Hallo.]", b"AUDIO[Wie geht es dir?]"]
    assert "stt_complete" in captured["status"]
    assert "ai_processing" in captured["status"]


async def test_empty_stt_speaks_error(make_pipeline, captured):
    p = make_pipeline(FakeSTT("   "))
    result = await p.run_turn(b"x" * 100000)

    assert not result.conversation_ended
    # The "nothing understood" error was spoken.
    assert len(captured["audio"]) == 1
    assert b"nichts verstanden" in captured["audio"][0]


async def test_conversation_end_event_propagates(make_pipeline, monkeypatch):
    monkeypatch.setattr(
        chat_client,
        "stream_reply",
        _fake_stream([
            ChatEvent("token", "Gern geschehen."),
            ChatEvent("conversation_end"),
            ChatEvent("done"),
        ]),
    )
    monkeypatch.setattr(pipeline, "stream_reply", chat_client.stream_reply)

    p = make_pipeline(FakeSTT("Danke"))
    result = await p.run_turn(b"x" * 100000)
    assert result.conversation_ended is True


async def test_ai_timeout_speaks_error(make_pipeline, captured, monkeypatch):
    async def _timeout_stream(*_a, **_kw):
        raise chat_client.ChatTimeout("AI-Timeout")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(pipeline, "stream_reply", _timeout_stream)

    p = make_pipeline(FakeSTT("Eine lange Frage"))
    result = await p.run_turn(b"x" * 100000)

    assert not result.conversation_ended
    assert len(captured["audio"]) == 1
    assert b"antwortet gerade nicht" in captured["audio"][0]


async def test_barge_in_stops_streaming(make_pipeline, captured, monkeypatch):
    p = make_pipeline(FakeSTT("Erzähl mir eine Geschichte"))

    async def _interrupting_stream(*_a, **_kw):
        yield ChatEvent("token", "Erster Satz. ")
        # Simulate a barge-in detected after the first sentence.
        p.interrupt()
        yield ChatEvent("token", "Zweiter Satz. ")
        yield ChatEvent("done")

    monkeypatch.setattr(pipeline, "stream_reply", _interrupting_stream)

    result = await p.run_turn(b"x" * 100000)

    assert result.interrupted is True
    # The second sentence is never spoken once the interrupt fires. With the
    # parallel TTS pipeline the first sentence may or may not have finished
    # streaming before the interrupt was observed — both outcomes are valid.
    assert captured["audio"] in ([], [b"AUDIO[Erster Satz.]"])
    assert b"AUDIO[Zweiter Satz.]" not in captured["audio"]


async def test_tts_pipeline_parallelism(monkeypatch):
    """
    BUG-2 regression: synthesis of sentence N+1 must overlap the sending of
    sentence N. A single ordered timeline records every synthesis-start and
    every audio-send; the test asserts sentence 2 synthesis begins before
    sentence 1 has finished sending all its chunks.
    """
    timeline: list[str] = []

    async def _slow_synthesize(text: str, target_rate=None, on_first_rate=None):
        if on_first_rate is not None:
            await on_first_rate(22050)
        timeline.append(f"synth-start:{text}")
        # Two chunks per sentence, with an await so the event loop can
        # interleave the next sentence's synthesis with this one's sending.
        for i in range(2):
            await asyncio.sleep(0.01)
            yield f"AUDIO[{text}#{i}]".encode()

    monkeypatch.setattr(tts, "synthesize", _slow_synthesize)

    async def _stream(*_a, **_kw):
        yield ChatEvent("token", "Satz eins. ")
        yield ChatEvent("token", "Satz zwei. ")
        yield ChatEvent("done")

    monkeypatch.setattr(pipeline, "stream_reply", _stream)

    sent: list[bytes] = []

    async def send_audio(b):
        await asyncio.sleep(0.01)  # simulate playback/transport time
        timeline.append(f"send:{b.decode()}")
        sent.append(b)

    async def send_status(_s):
        pass

    p = pipeline.VoicePipeline(
        session_id="sess-par",
        user_id="7",
        jwt_token="tok",
        stt=FakeSTT("Erzähl mir was"),
        send_status=send_status,
        send_audio=send_audio,
    )

    result = await p.run_turn(b"x" * 100000)

    assert not result.interrupted
    # Sentence order on the wire is preserved.
    assert sent == [
        b"AUDIO[Satz eins.#0]",
        b"AUDIO[Satz eins.#1]",
        b"AUDIO[Satz zwei.#0]",
        b"AUDIO[Satz zwei.#1]",
    ]
    # Pipeline overlap: "Satz zwei." synthesis starts BEFORE "Satz eins."
    # has finished sending its last chunk. Without parallelism the second
    # synth-start would only appear after both sentence-1 sends.
    second_synth = timeline.index("synth-start:Satz zwei.")
    last_send_s1 = timeline.index("send:AUDIO[Satz eins.#1]")
    assert second_synth < last_send_s1
