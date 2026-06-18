"""
Speaker identification using SpeechBrain ECAPA-TDNN (PROJ-43).

The model is loaded once at startup on the TITAN X GPU. Per-turn: extract a
192-D embedding from WAV audio, then compute cosine similarity against every
stored sample in the DB. The user whose sample set yields the highest average
similarity wins — provided it clears SPEAKER_THRESHOLD.

All heavy computation (model inference) runs in the asyncio thread pool so
it does not block the event loop.
"""
from __future__ import annotations

import asyncio
import io
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger("alice-speech-gateway.speaker_id")

_classifier = None  # EncoderClassifier, set by load_model()


def load_model(model_path: str, device: str = "cuda") -> None:
    """
    Load the ECAPA-TDNN model. Call once at gateway startup.

    model_path is the SpeechBrain savedir; the model weights are downloaded
    from HuggingFace Hub on first run (~85 MB) and cached there.
    """
    global _classifier
    try:
        from speechbrain.inference.speaker import EncoderClassifier
        _classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=model_path,
            run_opts={"device": device},
        )
        logger.info("Speaker-ID model loaded (device=%s, path=%s)", device, model_path)
    except Exception as exc:
        logger.error("Failed to load Speaker-ID model: %s — recognition disabled", exc)
        _classifier = None


def is_ready() -> bool:
    return _classifier is not None


def _extract_sync(wav_bytes: bytes) -> Optional[np.ndarray]:
    """Synchronous embedding extraction — runs in thread pool."""
    if _classifier is None:
        return None
    try:
        import torch
        import torchaudio

        signal, sr = torchaudio.load(io.BytesIO(wav_bytes))
        # Resample to 16 kHz (ECAPA-TDNN training rate)
        if sr != 16000:
            signal = torchaudio.functional.resample(signal, sr, 16000)
        # Mono
        if signal.shape[0] > 1:
            signal = signal.mean(0, keepdim=True)
        signal = signal.squeeze(0)  # (time,)
        with torch.no_grad():
            embedding = _classifier.encode_batch(signal.unsqueeze(0))  # (1, 1, D)
        return embedding.squeeze().cpu().numpy()  # (D,)
    except Exception as exc:
        logger.warning("Speaker-ID embedding failed: %s", exc)
        return None


async def extract_embedding(wav_bytes: bytes) -> Optional[np.ndarray]:
    """Async wrapper — offloads GPU inference to thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _extract_sync, wav_bytes)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def identify(
    query: np.ndarray,
    profiles: list[dict],
    threshold: float,
) -> tuple[Optional[str], float, Optional[str]]:
    """
    Find the best matching user for a query embedding.

    profiles: list of {"user_id": str, "display_name": str, "embeddings": [[float, ...]]}
    Returns (user_id, confidence, display_name). user_id is None if no profile
    clears the threshold.
    """
    best_user_id: Optional[str] = None
    best_display_name: Optional[str] = None
    best_score = 0.0

    for profile in profiles:
        stored: list[list[float]] = profile.get("embeddings") or []
        if not stored:
            continue
        scores = [_cosine(query, np.array(emb)) for emb in stored]
        avg = float(np.mean(scores))
        if avg > best_score:
            best_score = avg
            best_user_id = profile["user_id"]
            best_display_name = profile.get("display_name") or profile["user_id"]

    if best_score >= threshold:
        return best_user_id, best_score, best_display_name
    return None, best_score, None


async def identify_from_audio(
    wav_bytes: bytes,
    profiles: list[dict],
    threshold: float,
) -> tuple[Optional[str], float, Optional[str]]:
    """
    Extract embedding from wav_bytes and identify the speaker.

    Returns (user_id, confidence, display_name).
    user_id is None when no match clears the threshold or the model is unavailable.
    """
    if not is_ready() or not profiles:
        return None, 0.0, None
    embedding = await extract_embedding(wav_bytes)
    if embedding is None:
        return None, 0.0, None
    return identify(embedding, profiles, threshold)
