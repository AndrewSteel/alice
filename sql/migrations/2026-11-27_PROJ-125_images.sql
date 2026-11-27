-- PROJ-125: Images in the source of truth (alice-image-processing; register stages). Idempotent.
BEGIN;

-- ============================================================
-- 22. IMAGES IN THE SOURCE OF TRUTH (PROJ-125)
-- ============================================================
-- Images (kind `image`) are described (stage `extract`: EXIF, vision description,
-- title) and located (new stage `locate`) by alice-image-processing. No business
-- table for images: `classify` and `database` do not apply to them.

-- 22.1 Stages `classify` and `database` do not apply to images
UPDATE alice.pipeline_stages SET skip_kinds = array_append(skip_kinds, 'image')
 WHERE name IN ('classify', 'database') AND NOT ('image' = ANY(skip_kinds));
UPDATE alice.source_stages ss SET state = 'skipped', attempts = 0, last_error = NULL, next_retry_at = NULL,
       claim_token = NULL, started_at = NULL, rebuild_run = NULL
  FROM alice.sources s
 WHERE s.id = ss.source_id AND s.kind = 'image' AND ss.stage IN ('classify', 'database')
   AND ss.state <> 'skipped';

-- 22.2 New stage `locate` (place of an image from GPS), only for images
INSERT INTO alice.pipeline_stages (name, position, skip_kinds, resets_on_content_change)
VALUES ('locate', 25, '{document,email,audio,video}', FALSE)
ON CONFLICT (name) DO NOTHING;
INSERT INTO alice.source_stages (source_id, stage, state)
SELECT s.id, 'locate', CASE WHEN s.kind = 'image' THEN 'pending' ELSE 'skipped' END
  FROM alice.sources s
ON CONFLICT DO NOTHING;

-- Claims of new images before the backlog filter on the registration time
CREATE INDEX IF NOT EXISTS idx_sources_kind_created ON alice.sources(kind, created_at);

-- 22.3 First start of alice-image-processing: images registered before it are the backlog
CREATE TABLE IF NOT EXISTS alice.image_processing_state (
    id           INTEGER      PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    first_start  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 22.4 Geoapify calls per calendar day (Europe/Berlin), reserved before each call
CREATE TABLE IF NOT EXISTS alice.image_geocode_usage (
    day         DATE         PRIMARY KEY,
    calls       INTEGER      NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 22.5 Images triggered for a description one by one (sample, troubleshooting)
CREATE TABLE IF NOT EXISTS alice.image_describe_requests (
    source_id     VARCHAR(12)  PRIMARY KEY REFERENCES alice.sources(id) ON DELETE CASCADE,
    requested_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 22.6 RLS: only the service database user writes these tables
ALTER TABLE alice.image_processing_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.image_geocode_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.image_describe_requests ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['image_processing_state', 'image_geocode_usage', 'image_describe_requests'] LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I_select ON alice.%I', t, t);
        EXECUTE format('DROP POLICY IF EXISTS %I_insert ON alice.%I', t, t);
        EXECUTE format('DROP POLICY IF EXISTS %I_update ON alice.%I', t, t);
        EXECUTE format('DROP POLICY IF EXISTS %I_delete ON alice.%I', t, t);
        EXECUTE format('CREATE POLICY %I_select ON alice.%I FOR SELECT USING (TRUE)', t, t);
        EXECUTE format('CREATE POLICY %I_insert ON alice.%I FOR INSERT WITH CHECK (TRUE)', t, t);
        EXECUTE format('CREATE POLICY %I_update ON alice.%I FOR UPDATE USING (TRUE)', t, t);
        EXECUTE format('CREATE POLICY %I_delete ON alice.%I FOR DELETE USING (TRUE)', t, t);
    END LOOP;
END $$;

COMMIT;
