-- PROJ-118: Classification + field extraction (alice-document-classify). Idempotent.
-- A stage can go back to pending when certain frontmatter fields or the content part
-- (`content`) change, by another stage or by hand. classify: content and type.
BEGIN;

ALTER TABLE alice.pipeline_stages ADD COLUMN IF NOT EXISTS resets_on_fields TEXT[] NOT NULL DEFAULT '{}';

UPDATE alice.pipeline_stages SET resets_on_fields = '{content,type}'
 WHERE name = 'classify' AND resets_on_fields = '{}';

COMMIT;
