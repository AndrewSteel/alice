-- ============================================================
-- Migration 067 — PROJ-80: DMS-Vollständigkeits-Dashboard.
-- Widens dms_watched_folders.suggested_type to include 'Image',
-- so image inbox folders can be assigned a fixed type like the
-- six DMS-type folders (needed for the coverage matrix's
-- path-scan-per-type breakdown).
-- Apply against the alice database after init-schema.sql.
-- Safe to re-run (constraint drop/re-add is idempotent).
-- ============================================================

ALTER TABLE alice.dms_watched_folders DROP CONSTRAINT IF EXISTS dms_watched_folders_suggested_type_check;
ALTER TABLE alice.dms_watched_folders ADD CONSTRAINT dms_watched_folders_suggested_type_check CHECK (suggested_type IN (
    'Invoice', 'BankStatement', 'Document', 'Email',
    'SecuritySettlement', 'Contract', 'Image'
));
