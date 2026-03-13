-- ============================================================
-- PROJ-15: DMS Watched Folders — Schema Migration
-- Creates alice.dms_watched_folders table for NAS folder management.
-- Run: docker exec postgres psql -U user -d alice -f /path/to/009-proj15-dms-watched-folders.sql
-- ============================================================

BEGIN;

-- ============================================================
-- 1. Reusable trigger function for auto-updating updated_at
-- ============================================================

CREATE OR REPLACE FUNCTION alice.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 2. Table: alice.dms_watched_folders
-- ============================================================

CREATE TABLE alice.dms_watched_folders (
  id             SERIAL PRIMARY KEY,
  path           TEXT NOT NULL UNIQUE CHECK (char_length(path) <= 500),
  suggested_type TEXT CHECK (suggested_type IN (
    'Invoice', 'BankStatement', 'Document', 'Email',
    'SecuritySettlement', 'Contract'
  )),
  description    TEXT,
  enabled        BOOLEAN NOT NULL DEFAULT true,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 3. Indexes
-- ============================================================

CREATE INDEX idx_dms_watched_folders_enabled
  ON alice.dms_watched_folders(enabled);

-- ============================================================
-- 4. Auto-update trigger for updated_at
-- ============================================================

CREATE TRIGGER trg_dms_watched_folders_updated_at
  BEFORE UPDATE ON alice.dms_watched_folders
  FOR EACH ROW
  EXECUTE FUNCTION alice.set_updated_at();

-- ============================================================
-- 5. Row Level Security
-- ============================================================

ALTER TABLE alice.dms_watched_folders ENABLE ROW LEVEL SECURITY;

-- The n8n service account (table owner) bypasses RLS.
-- Permissive policy for any non-owner role that may access the table.
CREATE POLICY dms_watched_folders_allow_all ON alice.dms_watched_folders
  FOR ALL USING (true) WITH CHECK (true);

COMMIT;
