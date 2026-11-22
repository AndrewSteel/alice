-- PROJ-116: File detection (alice-file-detection). Idempotent.
BEGIN;

-- ============================================================
-- 17. FILE DETECTION (PROJ-116)
-- ============================================================
-- Working state of alice-file-detection. The source register (section 16) stays
-- the truth about sources and locations; these tables only mirror what the
-- detection service has seen on the NAS. Written only by alice-file-detection.

-- 17.1 Known files: one row per registered NAS path
CREATE TABLE IF NOT EXISTS alice.detect_files (
    path        TEXT         PRIMARY KEY,
    source_id   VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    folder      TEXT         NOT NULL,           -- watched folder (path) the file belongs to
    size        BIGINT       NOT NULL,
    mtime_ns    BIGINT       NOT NULL,
    first_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detect_files_folder ON alice.detect_files(folder);
CREATE INDEX IF NOT EXISTS idx_detect_files_source ON alice.detect_files(source_id);

-- 17.2 Directory state for the day scan (only equality of mtime counts)
CREATE TABLE IF NOT EXISTS alice.detect_dirs (
    path        TEXT         PRIMARY KEY,
    folder      TEXT         NOT NULL,
    parent      TEXT,
    mtime_ns    BIGINT       NOT NULL,
    confirmed   BOOLEAN      NOT NULL DEFAULT FALSE,  -- same mtime seen by two scans
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detect_dirs_folder ON alice.detect_dirs(folder);
CREATE INDEX IF NOT EXISTS idx_detect_dirs_parent ON alice.detect_dirs(parent);

-- 17.3 New files waiting for stability (same size + mtime in two scans)
CREATE TABLE IF NOT EXISTS alice.detect_pending (
    path        TEXT         PRIMARY KEY,
    folder      TEXT         NOT NULL,
    size        BIGINT       NOT NULL,
    mtime_ns    BIGINT       NOT NULL,
    first_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detect_pending_folder ON alice.detect_pending(folder);

-- 17.4 Detection problems (unreadable files), retried by every scan
CREATE TABLE IF NOT EXISTS alice.detect_problems (
    path        TEXT         PRIMARY KEY,
    folder      TEXT         NOT NULL,
    cause       TEXT         NOT NULL,
    first_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detect_problems_last_seen ON alice.detect_problems(last_seen DESC);

-- 17.5 Runs (day scan / nightly run) incl. the nightly summary (PROJ-122)
CREATE TABLE IF NOT EXISTS alice.detect_runs (
    id          BIGSERIAL    PRIMARY KEY,
    kind        VARCHAR(10)  NOT NULL CHECK (kind IN ('day', 'night')),
    trigger     VARCHAR(10)  NOT NULL DEFAULT 'schedule' CHECK (trigger IN ('schedule', 'manual', 'catchup')),
    state       VARCHAR(10)  NOT NULL DEFAULT 'running'
                CHECK (state IN ('running', 'done', 'paused', 'aborted', 'failed')),
    started_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    error       TEXT,
    summary     JSONB
);

CREATE INDEX IF NOT EXISTS idx_detect_runs_kind_started ON alice.detect_runs(kind, started_at DESC);

-- 17.6 RLS: only the service database user writes these tables
ALTER TABLE alice.detect_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.detect_dirs ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.detect_pending ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.detect_problems ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.detect_runs ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['detect_files', 'detect_dirs', 'detect_pending', 'detect_problems', 'detect_runs'] LOOP
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
