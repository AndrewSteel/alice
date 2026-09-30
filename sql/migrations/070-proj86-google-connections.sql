-- Migration: PROJ-86 Google API Infrastructure
-- Creates the table holding one OAuth connection per (Alice user, Google account).
-- Tokens are stored AES-256-CBC encrypted (key: GOOGLE_ENC_KEY in alice-google-connect).

-- ============================================================
-- GOOGLE CONNECTIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.google_connections (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                  UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    google_account           VARCHAR(255) NOT NULL,   -- Google account email address
    scopes                   TEXT[] NOT NULL DEFAULT '{}',  -- granted OAuth scopes, free list
    access_token_enc         TEXT NOT NULL,           -- AES-256-CBC encrypted
    access_token_expires_at  TIMESTAMPTZ NOT NULL,
    refresh_token_enc        TEXT NOT NULL,           -- AES-256-CBC encrypted
    status                   VARCHAR(20) NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active', 'error')),
    last_error               TEXT,
    created_at               TIMESTAMPTZ DEFAULT NOW(),
    updated_at               TIMESTAMPTZ DEFAULT NOW(),
    -- Scope extensions update the existing row instead of creating a duplicate.
    CONSTRAINT google_connections_user_account_uniq UNIQUE (user_id, google_account)
);

ALTER TABLE alice.google_connections ENABLE ROW LEVEL SECURITY;

CREATE POLICY google_connections_select ON alice.google_connections FOR SELECT USING (TRUE);
CREATE POLICY google_connections_insert ON alice.google_connections FOR INSERT WITH CHECK (TRUE);
CREATE POLICY google_connections_update ON alice.google_connections FOR UPDATE USING (TRUE);
CREATE POLICY google_connections_delete ON alice.google_connections FOR DELETE USING (TRUE);

CREATE INDEX IF NOT EXISTS idx_google_connections_user ON alice.google_connections(user_id);

CREATE OR REPLACE TRIGGER set_updated_at_google_connections
    BEFORE UPDATE ON alice.google_connections
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();
