-- ============================================================
-- Migration 012: PROJ-28 DMS Folder Sort Order
-- ============================================================
-- Adds sort_order column to alice.dms_watched_folders so admins
-- can control the processing order of DMS watch folders.
-- Run: docker exec postgres psql -U user -d alice -f /path/to/012-proj28-dms-folder-sort-order.sql
-- ============================================================

-- 1. Add sort_order column (default 0 for safety; backfilled below)
ALTER TABLE alice.dms_watched_folders
    ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;

-- 2. Backfill existing rows: preserve insertion order by using id
UPDATE alice.dms_watched_folders SET sort_order = id;

-- 3. Index for ORDER BY sort_order ASC queries
CREATE INDEX IF NOT EXISTS idx_dms_watched_folders_sort_order
    ON alice.dms_watched_folders (sort_order ASC);
