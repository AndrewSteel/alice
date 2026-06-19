"""
Configuration loader for alice-speech-gateway.

All tunables come from environment variables (see .env.example). The
device->user mapping and the interrupt-phrase list are loaded from YAML
files mounted via a Docker volume so they can be changed without a
container rebuild.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import yaml

logger = logging.getLogger("alice-speech-gateway.config")


@dataclass(frozen=True)
class Device:
    """A configured HA Voice device, keyed by its source IP in device-mapping.yaml.

    user_id removed in PROJ-43 — identity is now determined per-turn by Speaker-ID.
    """

    name: str
    room: str


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default)


# --- JWT ---
JWT_PUBLIC_KEY_PATH = _get("JWT_PUBLIC_KEY_PATH", "")
JWT_ALGORITHM = "RS256"

# --- STT ---
WHISPER_MODEL = _get("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = _get("WHISPER_DEVICE", "cuda")
# "default" lets CTranslate2 auto-select the best compute type for the GPU.
# On TITAN X (Maxwell): "float16" and "int8_float16" both fail (architecture
# does not support mixed-precision). Use "default" (~7 GB, best accuracy) or
# "int8" (~2 GB, lower accuracy). Set via WHISPER_COMPUTE_TYPE in .env.
WHISPER_COMPUTE_TYPE = _get("WHISPER_COMPUTE_TYPE", "default")
WHISPER_MODEL_DIR = _get("WHISPER_MODEL_DIR", "/data")
SPEECH_LANGUAGE = _get("SPEECH_LANGUAGE", "de")

# --- AI backend ---
CHAT_STREAM_URL = _get("CHAT_STREAM_URL", "http://alice-chat-stream:8003").rstrip("/")
AI_TIMEOUT_SECONDS = float(_get("AI_TIMEOUT_SECONDS", "15"))

# --- TTS ---
PIPER_URI = _get("PIPER_URI", "tcp://wyoming-piper:10200")

# --- Wyoming server ---
WYOMING_PORT = int(_get("WYOMING_PORT", "10300"))

# --- Conversation behaviour ---
SILENCE_TIMEOUT_SECONDS = float(_get("SILENCE_TIMEOUT_SECONDS", "30"))
MIN_AUDIO_SECONDS = float(_get("MIN_AUDIO_SECONDS", "0.5"))

# --- Config files ---
DEVICE_MAPPING_PATH = _get("DEVICE_MAPPING_PATH", "/config/device-mapping.yaml")
INTERRUPT_PHRASES_PATH = _get("INTERRUPT_PHRASES_PATH", "/config/interrupt-phrases.yaml")

# --- Logging ---
LOG_LEVEL = _get("LOG_LEVEL", "INFO").upper()

# --- Speaker Recognition (PROJ-43) ---
# asyncpg DSN; empty → speaker recognition disabled (no DB connection).
POSTGRES_DSN = _get("POSTGRES_DSN", "")
# HuggingFace / SpeechBrain model cache directory.
SPEAKER_MODEL_PATH = _get("SPEAKER_MODEL_PATH", "/data/speaker-model")
# Cosine similarity threshold: scores below this → Guest role.
SPEAKER_THRESHOLD = float(_get("SPEAKER_THRESHOLD", "0.75"))
# CUDA device for Speaker-ID model ("cuda" or "cpu").
SPEAKER_DEVICE = _get("SPEAKER_DEVICE", "cuda")

# Spoken waiting messages — played immediately when qwen3 starts reasoning (PROJ-48).
# On the first turn of a session the greeting replaces the waiting message (PROJ-43).
SPEECH_THINKING = {
    "du": "Warte bitte, ich muss kurz überlegen.",
    "sie": "Warten Sie bitte, ich muss kurz überlegen.",
}

# First-turn greeting waiting messages (llm sessions, PROJ-43).
# {name} is substituted with the speaker's display_name or "Gast".
SPEECH_GREETING_THINKING = {
    "known": "Hallo {name}, einen Moment…",   # U+2026 HORIZONTAL ELLIPSIS
    "guest": "Hallo Gast, was kann ich für dich tun?",
}

# Spoken error messages (German) — surfaced to the user as TTS audio.
SPEECH_ERRORS = {
    "stt_empty": "Ich habe nichts verstanden, bitte wiederhole das.",
    "audio_too_short": "Die Aufnahme war zu kurz, bitte sprich etwas länger.",
    "stt_failed": "Bei der Spracherkennung ist ein Fehler aufgetreten.",
    "ai_timeout": "Alice antwortet gerade nicht, bitte versuche es erneut.",
    "ai_failed": "Bei der Verarbeitung ist ein Fehler aufgetreten.",
    "unknown_device": "Dieses Gerät ist nicht bei Alice registriert.",
    "enrollment_not_admin": "Enrollment kann nur von einem Administrator gestartet werden.",
}

# Enrollment dialog prompts (PROJ-43).
SPEECH_ENROLLMENT = {
    "start_user":   "Ich starte die Einrollung eines neuen Nutzers. Wie lautet der Anzeigename?",
    "start_guest":  "Ich starte die Einrollung eines neuen Gastes. Wie lautet der Anzeigename?",
    "confirm_name": "Ich habe verstanden: {name}. Ist das korrekt? Ja oder Nein.",
    "ask_username": "Gut. Wie lautet der Benutzername? Bitte nur Buchstaben und Zahlen.",
    "confirm_username": "Ich habe verstanden: {username}. Ist das korrekt? Ja oder Nein.",
    "username_taken": "Der Benutzername {username} ist bereits vergeben. Bitte nenne einen anderen.",
    "retry_name":   "In Ordnung, bitte nenne den Anzeigenamen erneut.",
    "retry_username": "In Ordnung, bitte nenne den Benutzernamen erneut.",
    "ask_anrede":   "Welche Anrede bevorzugt die Person? Du oder Sie?",
    "ask_sprache":  "Welche Sprache? Deutsch oder Englisch?",
    "done_user":    "Einrollung abgeschlossen. {name} wurde als neuer Nutzer angelegt.",
    "done_guest":   "Einrollung abgeschlossen. {name} wurde als neuer Gast angelegt.",
    "save_failed":  "Die Einrollung konnte nicht gespeichert werden. Bitte versuche es erneut.",
    "aborted":      "Einrollung abgebrochen.",
}


def load_device_mapping(path: str = DEVICE_MAPPING_PATH) -> dict[str, Device]:
    """
    Load the source-IP -> Device mapping for Wyoming / HA Voice devices.

    Each entry maps a fixed device IP to a user_id plus a human-readable
    name and room (used for logging and, later, PROJ-43 speaker context).

    Returns an empty mapping (not an error) if the file is missing — every
    device then resolves as 'unknown' and receives a spoken error.
    """
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("Device mapping file not found: %s", path)
        return {}
    except yaml.YAMLError as exc:
        logger.error("Device mapping YAML is invalid: %s", exc)
        return {}

    raw = data.get("devices", {})
    mapping: dict[str, Device] = {}
    for ip, entry in raw.items():
        if not isinstance(entry, dict):
            logger.error("Skipping device mapping entry (expected fields, got %r): %r", entry, ip)
            continue
        name = str(entry.get("name") or ip).strip()
        room = str(entry.get("room") or "").strip()
        mapping[str(ip)] = Device(name=name, room=room)
    logger.info("Loaded %d device mappings", len(mapping))
    return mapping


def load_interrupt_phrases(path: str = INTERRUPT_PHRASES_PATH) -> list[str]:
    """
    Load the configurable barge-in interrupt-phrase list.

    Falls back to a small built-in German list if the file is missing,
    so barge-in still works on a fresh deployment.
    """
    fallback = ["stop", "stopp", "halt", "warte", "moment"]
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("Interrupt phrases file not found: %s — using fallback", path)
        return fallback
    except yaml.YAMLError as exc:
        logger.error("Interrupt phrases YAML is invalid: %s — using fallback", exc)
        return fallback

    phrases = [str(p).strip().lower() for p in data.get("phrases", []) if str(p).strip()]
    if not phrases:
        logger.warning("Interrupt phrases file empty — using fallback")
        return fallback
    logger.info("Loaded %d interrupt phrases", len(phrases))
    return phrases
