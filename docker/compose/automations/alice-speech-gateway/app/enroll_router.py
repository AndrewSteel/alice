"""
HTTP enrollment endpoints for the WebApp path (PROJ-43).

POST   /enroll               — upload 5 audio files, extract embeddings, store
DELETE /enroll/{user_id}     — delete a voice profile (admin only)
GET    /enroll/profiles      — list all enrolled users (admin only)
PATCH  /enroll/{user_id}/allow — toggle allow_voice_enrollment (admin only)

All endpoints require a valid JWT. user_id always comes from the verified
token payload — never from the request body.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import config
from .auth import AuthError, verify_token
from .speaker_db import (
    delete_embeddings,
    get_user,
    is_ready as db_ready,
    list_enrolled_profiles,
    save_embeddings,
    set_allow_voice_enrollment,
)
from .speaker_id import extract_embedding, is_ready as sid_ready


def is_ready() -> bool:
    """Both DB pool and speaker model must be up."""
    return db_ready() and sid_ready()

logger = logging.getLogger("alice-speech-gateway.enroll")

router = APIRouter(prefix="/enroll", tags=["enrollment"])

# ---------- Auth dependency ----------

from fastapi import Header
from typing import Optional


async def _require_auth(authorization: Optional[str] = Header(default=None)) -> dict:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):]
    try:
        return verify_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


async def _require_admin(payload: dict = Depends(_require_auth)) -> dict:
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin-Berechtigung erforderlich")
    return payload


# ---------- Endpoints ----------

@router.post("")
async def enroll_self(
    files: list[UploadFile],
    payload: dict = Depends(_require_auth),
) -> JSONResponse:
    """
    Upload 5 audio samples (WAV/WebM) and store the voice profile for the
    authenticated user.

    The user must have allow_voice_enrollment = true (or be admin).
    """
    user_id: str = payload["user_id"]

    if not is_ready():
        raise HTTPException(status_code=503, detail="Speaker-ID not available")

    # Verify user is allowed to enroll
    user = await get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Nutzer nicht gefunden")

    is_admin = payload.get("role") == "admin"
    if not is_admin and not user.get("allow_voice_enrollment"):
        raise HTTPException(status_code=403, detail="Stimmregistrierung für diesen Nutzer nicht aktiviert")

    if len(files) < 5:
        raise HTTPException(status_code=400, detail="Mindestens 5 Audioaufnahmen erforderlich")

    embeddings: list[list[float]] = []
    for f in files[:5]:
        audio_bytes = await f.read()
        emb = await extract_embedding(audio_bytes)
        if emb is None:
            raise HTTPException(status_code=422, detail=f"Embedding für Datei {f.filename!r} fehlgeschlagen")
        embeddings.append(emb.tolist())

    await save_embeddings(user_id, embeddings)
    logger.info("WebApp enrollment completed for user %s (%d samples)", user_id, len(embeddings))
    return JSONResponse({"status": "ok", "samples": len(embeddings)})


@router.get("/profiles")
async def get_profiles(_: dict = Depends(_require_admin)) -> JSONResponse:
    """List all enrolled users with sample count (admin only)."""
    if not is_ready():
        raise HTTPException(status_code=503, detail="Speaker-ID not available")
    profiles = await list_enrolled_profiles()
    # Convert datetime objects for JSON serialisation
    result = []
    for p in profiles:
        result.append({
            "user_id":      p["user_id"],
            "username":     p["username"],
            "display_name": p["display_name"],
            "role":         p["role"],
            "sample_count": p["sample_count"],
            "created_at":   p["created_at"].isoformat() if p.get("created_at") else None,
        })
    return JSONResponse(result)


@router.delete("/{user_id}")
async def delete_profile(user_id: str, _: dict = Depends(_require_admin)) -> JSONResponse:
    """Delete a user's voice profile (admin only)."""
    if not is_ready():
        raise HTTPException(status_code=503, detail="Speaker-ID not available")
    deleted = await delete_embeddings(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Stimmprofil nicht gefunden")
    return JSONResponse({"status": "deleted", "user_id": user_id})


class _AllowBody(BaseModel):
    allow: bool


@router.patch("/{user_id}/allow")
async def toggle_enrollment_permission(
    user_id: str,
    body: _AllowBody,
    _: dict = Depends(_require_admin),
) -> JSONResponse:
    """Toggle allow_voice_enrollment for a user (admin only)."""
    user = await get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Nutzer nicht gefunden")
    await set_allow_voice_enrollment(user_id, body.allow)
    return JSONResponse({"status": "ok", "user_id": user_id, "allow_voice_enrollment": body.allow})
