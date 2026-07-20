-- ============================================================
-- Migration 065 — PROJ-65: Effective-Permissions API & fehlende
-- System-Flags.
-- Apply against the alice database after init-schema.sql.
-- Safe to re-run (ADD COLUMN IF NOT EXISTS, idempotent jsonb
-- merge, admin backfill re-sets the same values).
-- ============================================================

-- 1. Add the three new columns.
ALTER TABLE alice.permissions_system
    ADD COLUMN IF NOT EXISTS can_manage_dms_folders BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS can_view_chat_archive  BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS can_manage_mailboxes   BOOLEAN DEFAULT FALSE;

-- 2. Update role templates (idempotent merge of the three new keys).
--    admin -> true; user/guest/child -> false (matches today's de-facto
--    behaviour, no behaviour change until PROJ-66 consumes the flags).
UPDATE alice.role_templates
SET system_permissions = system_permissions
    || '{"can_manage_dms_folders": true, "can_view_chat_archive": true, "can_manage_mailboxes": true}'::jsonb
WHERE role = 'admin';

UPDATE alice.role_templates
SET system_permissions = system_permissions
    || '{"can_manage_dms_folders": false, "can_view_chat_archive": false, "can_manage_mailboxes": false}'::jsonb
WHERE role IN ('user', 'guest', 'child');

-- 3. Backfill existing admin users' permission rows to true.
--    Non-admin users keep the FALSE default (untouched).
UPDATE alice.permissions_system ps
SET can_manage_dms_folders = TRUE,
    can_view_chat_archive  = TRUE,
    can_manage_mailboxes   = TRUE,
    updated_at             = NOW()
FROM alice.users u
WHERE ps.user_id = u.id
  AND u.role = 'admin';

-- Reporting only — admin permission rows now fully set.
SELECT u.id, u.username
FROM alice.permissions_system ps
JOIN alice.users u ON u.id = ps.user_id
WHERE u.role = 'admin'
  AND ps.can_manage_dms_folders
  AND ps.can_view_chat_archive
  AND ps.can_manage_mailboxes
ORDER BY u.username;
