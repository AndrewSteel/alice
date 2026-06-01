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

import yaml

logger = logging.getLogger("alice-speech-gateway.config")


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default)


# --- JWT ---
JWT_PUBLIC_KEY_PATH = _get("JWT_PUBLIC_KEY_PATH", "")
JWT_ALGORITHM = "RS256"

# --- STT ---
WHISPER_MODEL = _get("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = _get("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = _get("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_MODEL_DIR = _get("WHISPER_MODEL_DIR", "/data")
SPEECH_LANGUAGE = _get("SPEECH_LANGUAGE", "de")

# --- AI backend ---
CHAT_STREAM_URL = _get("CHAT_STREAM_URL", "http://alice-chat-stream:8003").rstrip("/")
AI_TIMEOUT_SECONDS = float(_get("AI_TIMEOUT_SECONDS", "15"))

# --- TTS ---
PIPER_URI = _get("PIPER_URI", "tcp://wyoming-piper:10200")

# --- Wyoming server ---
WYOMING_PORT = int(_get("WYOMING_PORT", "10302"))

# --- Conversation behaviour ---
SILENCE_TIMEOUT_SECONDS = float(_get("SILENCE_TIMEOUT_SECONDS", "30"))
MIN_AUDIO_SECONDS = float(_get("MIN_AUDIO_SECONDS", "0.5"))

# --- Config files ---
DEVICE_MAPPING_PATH = _get("DEVICE_MAPPING_PATH", "/config/device-mapping.yaml")
INTERRUPT_PHRASES_PATH = _get("INTERRUPT_PHRASES_PATH", "/config/interrupt-phrases.yaml")

# --- Logging ---
LOG_LEVEL = _get("LOG_LEVEL", "INFO").upper()

# Spoken error messages (German) — surfaced to the user as TTS audio.
SPEECH_ERRORS = {
    "stt_empty": "Ich habe nichts verstanden, bitte wiederhole das.",
    "audio_too_short": "Die Aufnahme war zu kurz, bitte sprich etwas länger.",
    "stt_failed": "Bei der Spracherkennung ist ein Fehler aufgetreten.",
    "ai_timeout": "Alice antwortet gerade nicht, bitte versuche es erneut.",
    "ai_failed": "Bei der Verarbeitung ist ein Fehler aufgetreten.",
    "unknown_device": "Dieses Gerät ist nicht bei Alice registriert.",
}


def load_device_mapping(path: str = DEVICE_MAPPING_PATH) -> dict[str, str]:
    """
    Load the Wyoming device-id -> user_id mapping.

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
    mapping: dict[str, str] = {}
    for device_id, user_id in raw.items():
        if not user_id or not str(user_id).strip():
            logger.error("Skipping invalid device mapping entry: %r -> %r", device_id, user_id)
            continue
        mapping[str(device_id)] = str(user_id)
    logger.info("Loaded %d device->user mappings", len(mapping))
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
