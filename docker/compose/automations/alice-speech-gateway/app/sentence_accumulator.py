"""
Sentence accumulator — splits a token stream into complete sentences.

The LLM emits tokens; TTS works best (and starts soonest) on whole
sentences. This buffers tokens and flushes a sentence as soon as a
terminator (. ! ? or newline) is seen, so sentence 1 reaches Piper while
the LLM is still generating sentence 2.

Abbreviations are deliberately NOT handled — a rare mid-sentence split is
acceptable for TTS and far cheaper than a full NLP sentence segmenter.
"""
from __future__ import annotations

_TERMINATORS = ".!?\n"


class SentenceAccumulator:
    """Stateful buffer. Feed tokens in; pull complete sentences out."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, token: str) -> list[str]:
        """
        Add a token; return any complete sentences it completed.

        A sentence is everything up to and including a terminator. Multiple
        sentences in one token are all returned.
        """
        if not token:
            return []
        self._buffer += token
        sentences: list[str] = []
        while True:
            idx = self._next_terminator(self._buffer)
            if idx == -1:
                break
            sentence = self._buffer[: idx + 1].strip()
            self._buffer = self._buffer[idx + 1:]
            if sentence:
                sentences.append(sentence)
        return sentences

    def flush(self) -> str | None:
        """Return any trailing partial sentence (no terminator). Clears the buffer."""
        leftover = self._buffer.strip()
        self._buffer = ""
        return leftover or None

    @staticmethod
    def _next_terminator(text: str) -> int:
        for i, ch in enumerate(text):
            if ch in _TERMINATORS:
                return i
        return -1
