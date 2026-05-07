-- ============================================================
-- Migration 013: PROJ-29 BankTransaction Permissions
-- ============================================================
-- Adds the new doc_type 'BankTransaction' to the
-- alice.permissions_dms CHECK constraint and ensures every user
-- that already has a BankStatement permission row also gets a
-- matching BankTransaction permission row with identical flags.
--
-- BankTransaction objects contain the same sensitive financial
-- data as their parent BankStatement, so the permission level
-- must be identical.
--
-- Run: docker exec postgres psql -U user -d alice -f /path/to/013-proj29-bank-transaction-permissions.sql
-- ============================================================

BEGIN;

-- ============================================================
-- 1. Update CHECK constraint to allow doc_type = 'BankTransaction'
-- ============================================================

ALTER TABLE alice.permissions_dms
    DROP CONSTRAINT IF EXISTS permissions_dms_doc_type_check;

ALTER TABLE alice.permissions_dms
    ADD CONSTRAINT permissions_dms_doc_type_check
    CHECK (doc_type IN (
        'Invoice',
        'BankStatement',
        'BankTransaction',
        'SecuritySettlement',
        'Document',
        'Email',
        'Contract',
        '*'
    ));

-- ============================================================
-- 2. Backfill: clone every BankStatement permission row to a
--    matching BankTransaction permission row (same flags).
--    Skip users that already have a BankTransaction row to make
--    this migration idempotent.
-- ============================================================

INSERT INTO alice.permissions_dms (
    user_id,
    doc_type,
    can_read,
    can_create,
    can_update,
    can_delete,
    can_download,
    filter_own_only,
    allowed_categories,
    max_amount_visible,
    created_at,
    updated_at
)
SELECT
    bs.user_id,
    'BankTransaction'        AS doc_type,
    bs.can_read,
    bs.can_create,
    bs.can_update,
    bs.can_delete,
    bs.can_download,
    bs.filter_own_only,
    bs.allowed_categories,
    bs.max_amount_visible,
    NOW(),
    NOW()
FROM alice.permissions_dms bs
WHERE bs.doc_type = 'BankStatement'
  AND NOT EXISTS (
      SELECT 1
      FROM alice.permissions_dms bt
      WHERE bt.user_id = bs.user_id
        AND bt.doc_type = 'BankTransaction'
  );

-- ============================================================
-- 3. role_templates: extend dms_permissions JSON seed data so
--    new users get a BankTransaction permission row that mirrors
--    their BankStatement row.
-- ============================================================

UPDATE alice.role_templates
SET dms_permissions = dms_permissions || jsonb_build_array(
    jsonb_set(
        (SELECT elem
         FROM jsonb_array_elements(dms_permissions) AS elem
         WHERE elem->>'doc_type' = 'BankStatement'
         LIMIT 1),
        '{doc_type}',
        '"BankTransaction"'
    )
)
WHERE dms_permissions IS NOT NULL
  -- Only roles that have a BankStatement entry but no BankTransaction entry yet
  AND EXISTS (
      SELECT 1 FROM jsonb_array_elements(dms_permissions) AS e
      WHERE e->>'doc_type' = 'BankStatement'
  )
  AND NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements(dms_permissions) AS e
      WHERE e->>'doc_type' = 'BankTransaction'
  );

COMMIT;
