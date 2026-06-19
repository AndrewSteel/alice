-- ============================================================
-- Migration 015 — PROJ-43: Speaker Recognition
-- Apply against the alice database after init-schema.sql.
-- Safe to re-run (uses IF NOT EXISTS / DO NOTHING patterns).
-- ============================================================

-- allow_voice_enrollment: controls whether a user's profile page shows
-- the "Stimmregistrierung" button. Admin-only toggle per user.
ALTER TABLE alice.users
    ADD COLUMN IF NOT EXISTS allow_voice_enrollment BOOLEAN DEFAULT false;

-- Note: speaker_embeddings JSONB DEFAULT '[]' and
-- speaker_enrollment_complete BOOLEAN DEFAULT FALSE already exist on
-- alice.users from the initial schema (Phase 2 placeholder).
-- PROJ-43 uses those columns directly; no separate speaker_profiles table needed.
-- Layout: speaker_embeddings = [[v1, v2, ...], [v1, v2, ...], ...]
--          Each inner array is one 192-D ECAPA-TDNN embedding vector.

-- Index: fast lookup of enrolled users on every Wyoming turn.
CREATE INDEX IF NOT EXISTS idx_users_speaker_enrolled
    ON alice.users (speaker_enrollment_complete, is_active)
    WHERE speaker_enrollment_complete = TRUE AND is_active = TRUE;
