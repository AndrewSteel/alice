-- ============================================================
-- Migration 066 — PROJ-75: Image search & display.
-- Adds the 'Image' doc_type to permissions_dms, grants the
-- 'user' role read access + the search_images tool.
-- Apply against the alice database after init-schema.sql.
-- Safe to re-run (constraint drop/re-add, idempotent jsonb
-- merge, backfill uses ON CONFLICT / existence checks).
-- ============================================================

-- 1. Widen the doc_type CHECK constraint to include 'Image'.
ALTER TABLE alice.permissions_dms DROP CONSTRAINT IF EXISTS permissions_dms_doc_type_check;
ALTER TABLE alice.permissions_dms ADD CONSTRAINT permissions_dms_doc_type_check CHECK (doc_type IN (
    'Invoice', 'BankStatement', 'BankTransaction',
    'SecuritySettlement', 'Document', 'Email', 'Contract', 'Image', '*'
));

-- 2. Add 'Image' (read-only) to the 'user' role template's dms_permissions,
--    unless already present (re-run safety).
UPDATE alice.role_templates
SET dms_permissions = dms_permissions
    || '[{"doc_type": "Image", "can_read": true, "can_create": false, "can_update": false, "can_delete": false, "can_download": false}]'::jsonb
WHERE role = 'user'
  AND NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements(dms_permissions) e WHERE e->>'doc_type' = 'Image'
  );

-- 3. Add 'search_images' to the 'user' role template's tools_allowed.
UPDATE alice.role_templates
SET assistant_permissions = jsonb_set(
    assistant_permissions,
    '{tools_allowed}',
    (assistant_permissions->'tools_allowed') || '["search_images"]'::jsonb
)
WHERE role = 'user'
  AND NOT (assistant_permissions->'tools_allowed' ? 'search_images');

-- 4. Backfill existing 'user'-role users with the new Image permission row.
INSERT INTO alice.permissions_dms (user_id, doc_type, can_read, can_create, can_update, can_delete, can_download)
SELECT u.id, 'Image', TRUE, FALSE, FALSE, FALSE, FALSE
FROM alice.users u
WHERE u.role = 'user'
ON CONFLICT (user_id, doc_type) DO NOTHING;

-- 5. Backfill existing 'user'-role users' tools_allowed with search_images.
UPDATE alice.permissions_assistant pa
SET tools_allowed = tools_allowed || '["search_images"]'::jsonb,
    updated_at     = NOW()
FROM alice.users u
WHERE pa.user_id = u.id
  AND u.role = 'user'
  AND NOT (tools_allowed ? 'search_images');

-- Admin (doc_type '*', tools_allowed ["*"]) and guest/child (doc_type '*'
-- can_read=false) are covered automatically by their existing wildcard rows
-- — no data change needed for those roles (see PROJ-75 acceptance criteria).

-- Reporting only — confirms the backfill.
SELECT u.id, u.username, pd.can_read AS image_can_read, pa.tools_allowed ? 'search_images' AS has_search_images
FROM alice.users u
JOIN alice.permissions_dms pd ON pd.user_id = u.id AND pd.doc_type = 'Image'
JOIN alice.permissions_assistant pa ON pa.user_id = u.id
WHERE u.role = 'user'
ORDER BY u.username;
