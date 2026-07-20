-- ============================================================
-- Migration 063 — PROJ-63: Backend Sprachcode-Offenheit
-- Apply against the alice database (no schema change, data-only).
-- Safe to re-run: only exact word-form matches are rewritten;
-- already-migrated codes, NULL, and unknown/manual values are
-- left untouched.
-- ============================================================

-- Rewrite alice.user_profiles.preferences.sprache from word-form
-- ("deutsch"/"englisch") to ISO 639-1 codes ("de"/"en"), consistent
-- with alice-auth's/alice-chat-stream's new language configuration.

BEGIN;

UPDATE alice.user_profiles
SET preferences = jsonb_set(preferences, '{sprache}', '"de"'),
    last_updated = NOW()
WHERE preferences->>'sprache' = 'deutsch';

UPDATE alice.user_profiles
SET preferences = jsonb_set(preferences, '{sprache}', '"en"'),
    last_updated = NOW()
WHERE preferences->>'sprache' = 'englisch';

COMMIT;

-- Reporting only — rows now holding a migrated ISO code, and rows
-- intentionally left untouched (present but not deutsch/englisch).
SELECT user_id, preferences->>'sprache' AS sprache
FROM alice.user_profiles
WHERE preferences->>'sprache' IN ('de', 'en')
ORDER BY user_id;

SELECT user_id, preferences->>'sprache' AS sprache
FROM alice.user_profiles
WHERE preferences ? 'sprache'
  AND preferences->>'sprache' NOT IN ('de', 'en')
ORDER BY user_id;
