"""
ESPHome voice enrollment state machine (PROJ-43).

Triggered when the STT transcript matches an enrollment intent. Drives a
multi-turn dialog via the Wyoming pipeline to collect display_name, username,
anrede, sprache, and 5 voice samples from the conversation turns.

The Wyoming handler creates an EnrollmentSession, feeds each turn's transcript
and audio to process_turn(), speaks the returned prompt, then calls
finish() to write the user to the database.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("alice-speech-gateway.enrollment")

# ---------- Intent detection ----------

_ENROLLMENT_PATTERNS = [
    # Nutzer / user
    r"lass\s+uns\s+(einen\s+)?neuen\s+nutzer\s+(aufnehmen|einrollen|registrieren)",
    r"neuen\s+nutzer\s+(aufnehmen|einrollen|registrieren)",
    r"nutzer\s+(aufnehmen|einrollen|registrieren)",
    # Gast / guest
    r"lass\s+uns\s+(einen\s+)?neuen\s+gast\s+(aufnehmen|einrollen|registrieren)",
    r"neuen\s+gast\s+(aufnehmen|einrollen|registrieren)",
    r"gast\s+(aufnehmen|einrollen|registrieren)",
]

_ENROLLMENT_RE = [re.compile(p) for p in _ENROLLMENT_PATTERNS]


def is_enrollment_intent(transcript: str) -> tuple[bool, str]:
    """
    Detect enrollment trigger in a transcript.

    Returns (is_trigger, role) where role is 'user' or 'guest'.
    """
    text = transcript.lower().strip()
    for pattern in _ENROLLMENT_RE:
        if pattern.search(text):
            role = "guest" if "gast" in text else "user"
            return True, role
    return False, ""


# ---------- State machine ----------

class _State(Enum):
    ASKING_DISPLAY_NAME     = auto()
    CONFIRMING_DISPLAY_NAME = auto()
    ASKING_USERNAME         = auto()
    CONFIRMING_USERNAME     = auto()
    ASKING_ANREDE           = auto()
    ASKING_SPRACHE          = auto()
    DONE                    = auto()
    ABORTED                 = auto()


def _is_yes(text: str) -> bool:
    t = text.lower().strip().rstrip(".!?,")
    return any(w in t for w in ("ja", "yes", "korrekt", "richtig", "stimmt", "genau", "jo"))


def _clean_username(raw: str) -> str:
    """Lowercase, remove spaces and punctuation, keep letters/digits/underscores."""
    cleaned = re.sub(r"[^a-z0-9_]", "", raw.lower().replace(" ", "_").replace("-", "_"))
    return cleaned or raw.lower()


@dataclass
class EnrollmentSession:
    """
    One enrollment conversation. Feed turns in; read .is_done when finished.

    username_checker: async callable (username: str) -> bool (True = taken).
    """

    role: str  # 'user' | 'guest'
    username_checker: Optional[Callable[[str], Awaitable[bool]]] = None

    # Collected data
    display_name: str = ""
    username: str = ""
    anrede: str = "du"
    sprache: str = "deutsch"

    # Audio samples from the dialog turns (used for embedding)
    audio_samples: list[bytes] = field(default_factory=list)

    _state: _State = field(default=_State.ASKING_DISPLAY_NAME, init=False)
    _pending_display_name: str = field(default="", init=False)
    _pending_username: str = field(default="", init=False)

    @property
    def is_done(self) -> bool:
        return self._state in (_State.DONE, _State.ABORTED)

    @property
    def succeeded(self) -> bool:
        return self._state == _State.DONE

    def first_prompt(self) -> str:
        """Spoken prompt before the first user input is collected."""
        from . import config
        key = "start_guest" if self.role == "guest" else "start_user"
        return config.SPEECH_ENROLLMENT[key]

    async def process_turn(self, transcript: str, audio: bytes) -> str:
        """
        Process one dialog turn and return the prompt to speak next.

        Always appends the audio sample for later embedding, even on retries.
        """
        from . import config

        self.audio_samples.append(audio)
        text = transcript.strip()

        if self._state == _State.ASKING_DISPLAY_NAME:
            self._pending_display_name = text
            self._state = _State.CONFIRMING_DISPLAY_NAME
            return config.SPEECH_ENROLLMENT["confirm_name"].format(name=text)

        if self._state == _State.CONFIRMING_DISPLAY_NAME:
            if _is_yes(text):
                self.display_name = self._pending_display_name
                self._state = _State.ASKING_USERNAME
                return config.SPEECH_ENROLLMENT["ask_username"]
            else:
                self._state = _State.ASKING_DISPLAY_NAME
                return config.SPEECH_ENROLLMENT["retry_name"]

        if self._state == _State.ASKING_USERNAME:
            self._pending_username = _clean_username(text)
            self._state = _State.CONFIRMING_USERNAME
            return config.SPEECH_ENROLLMENT["confirm_username"].format(
                username=self._pending_username
            )

        if self._state == _State.CONFIRMING_USERNAME:
            if _is_yes(text):
                # Check for username collision
                if self.username_checker and await self.username_checker(self._pending_username):
                    self._state = _State.ASKING_USERNAME
                    return config.SPEECH_ENROLLMENT["username_taken"].format(
                        username=self._pending_username
                    )
                self.username = self._pending_username
                self._state = _State.ASKING_ANREDE
                return config.SPEECH_ENROLLMENT["ask_anrede"]
            else:
                self._state = _State.ASKING_USERNAME
                return config.SPEECH_ENROLLMENT["retry_username"]

        if self._state == _State.ASKING_ANREDE:
            self.anrede = "sie" if "sie" in text.lower() else "du"
            self._state = _State.ASKING_SPRACHE
            return config.SPEECH_ENROLLMENT["ask_sprache"]

        if self._state == _State.ASKING_SPRACHE:
            if "englisch" in text.lower() or "english" in text.lower():
                self.sprache = "englisch"
            else:
                self.sprache = "deutsch"
            self._state = _State.DONE
            key = "done_guest" if self.role == "guest" else "done_user"
            return config.SPEECH_ENROLLMENT[key].format(name=self.display_name)

        # Should not reach here
        self._state = _State.ABORTED
        return config.SPEECH_ENROLLMENT["aborted"]

    def abort(self) -> None:
        self._state = _State.ABORTED

    def get_sample_audio(self) -> list[bytes]:
        """Return up to 5 audio samples for embedding extraction."""
        return self.audio_samples[:5]
