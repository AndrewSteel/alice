-- ============================================================
-- PROJ-19: Rename DMS doc types from German to English
-- Updates CHECK constraints and seed data in permissions_dms,
-- role_templates, and dms_watched_folders to use English
-- collection names matching Weaviate schema.
--
-- Mapping:
--   Rechnung           → Invoice
--   Kontoauszug        → BankStatement
--   WertpapierAbrechnung → SecuritySettlement
--   Dokument           → Document
--   Vertrag            → Contract
--   Email              → Email (no change)
--
-- Run: docker exec postgres psql -U user -d alice -f /path/to/010-proj19-english-doc-types.sql
-- ============================================================

BEGIN;

-- ============================================================
-- 1. permissions_dms: rename existing rows, then swap constraint
-- ============================================================

-- Drop old constraint first (still allows old German values during UPDATE)
ALTER TABLE alice.permissions_dms
    DROP CONSTRAINT IF EXISTS permissions_dms_doc_type_check;

-- Rename existing rows to English
UPDATE alice.permissions_dms SET doc_type = 'Invoice'            WHERE doc_type = 'Rechnung';
UPDATE alice.permissions_dms SET doc_type = 'BankStatement'      WHERE doc_type = 'Kontoauszug';
UPDATE alice.permissions_dms SET doc_type = 'SecuritySettlement' WHERE doc_type = 'WertpapierAbrechnung';
UPDATE alice.permissions_dms SET doc_type = 'Document'           WHERE doc_type = 'Dokument';
UPDATE alice.permissions_dms SET doc_type = 'Contract'           WHERE doc_type = 'Vertrag';

-- Now add new constraint (all rows already use English values)
ALTER TABLE alice.permissions_dms
    ADD CONSTRAINT permissions_dms_doc_type_check
    CHECK (doc_type IN (
        'Invoice',
        'BankStatement',
        'SecuritySettlement',
        'Document',
        'Email',
        'Contract',
        '*'
    ));

-- ============================================================
-- 3. role_templates: update dms_permissions JSON seed data
-- ============================================================

UPDATE alice.role_templates
SET dms_permissions = (
    SELECT jsonb_agg(
        CASE elem->>'doc_type'
            WHEN 'Rechnung'            THEN jsonb_set(elem, '{doc_type}', '"Invoice"')
            WHEN 'Kontoauszug'         THEN jsonb_set(elem, '{doc_type}', '"BankStatement"')
            WHEN 'WertpapierAbrechnung' THEN jsonb_set(elem, '{doc_type}', '"SecuritySettlement"')
            WHEN 'Dokument'            THEN jsonb_set(elem, '{doc_type}', '"Document"')
            WHEN 'Vertrag'             THEN jsonb_set(elem, '{doc_type}', '"Contract"')
            ELSE elem
        END
    )
    FROM jsonb_array_elements(dms_permissions) AS elem
)
WHERE dms_permissions IS NOT NULL
  AND dms_permissions::text ~ 'Rechnung|Kontoauszug|WertpapierAbrechnung|Dokument|Vertrag';

-- ============================================================
-- 4. dms_watched_folders: rename existing rows, then swap constraint
-- ============================================================

ALTER TABLE alice.dms_watched_folders
    DROP CONSTRAINT IF EXISTS dms_watched_folders_suggested_type_check;

UPDATE alice.dms_watched_folders SET suggested_type = 'Invoice'            WHERE suggested_type = 'Rechnung';
UPDATE alice.dms_watched_folders SET suggested_type = 'BankStatement'      WHERE suggested_type = 'Kontoauszug';
UPDATE alice.dms_watched_folders SET suggested_type = 'SecuritySettlement' WHERE suggested_type = 'WertpapierAbrechnung';
UPDATE alice.dms_watched_folders SET suggested_type = 'Document'           WHERE suggested_type = 'Dokument';
UPDATE alice.dms_watched_folders SET suggested_type = 'Contract'           WHERE suggested_type = 'Vertrag';

ALTER TABLE alice.dms_watched_folders
    ADD CONSTRAINT dms_watched_folders_suggested_type_check
    CHECK (suggested_type IN (
        'Invoice', 'BankStatement', 'Document', 'Email',
        'SecuritySettlement', 'Contract'
    ));

COMMIT;
