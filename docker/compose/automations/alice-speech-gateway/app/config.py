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
    """A configured HA Voice device, keyed by its source IP in device-mapping.yaml."""

    user_id: str
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
        user_id = entry.get("user_id")
        if not user_id or not str(user_id).strip():
            logger.error("Skipping device mapping entry without user_id: %r", ip)
            continue
        name = str(entry.get("name") or ip).strip()
        room = str(entry.get("room") or "").strip()
        mapping[str(ip)] = Device(user_id=str(user_id).strip(), name=name, room=room)
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
