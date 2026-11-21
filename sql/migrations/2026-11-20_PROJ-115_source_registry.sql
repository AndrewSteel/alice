-- PROJ-115: Source-of-truth registry (alice-source-registry). Idempotent.
BEGIN;

-- ============================================================
-- 16. SOURCE OF TRUTH REGISTRY (PROJ-115)
-- ============================================================
-- Register of all sources (unique content = hash) of the source-of-truth repo,
-- their locations, mail parents and the processing state per pipeline stage.
-- Written only by alice-source-registry; no end-user access.

-- 16.1 Pipeline stages: extensible list, a new stage is a new row
CREATE TABLE IF NOT EXISTS alice.pipeline_stages (
    name                      VARCHAR(40) PRIMARY KEY CHECK (name ~ '^[a-z][a-z0-9_]{0,39}$'),
    position                  INTEGER     NOT NULL DEFAULT 100,
    skip_kinds                TEXT[]      NOT NULL DEFAULT '{}',
    resets_on_content_change  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO alice.pipeline_stages (name, position, skip_kinds, resets_on_content_change) VALUES
    ('detect',    10, '{}',              FALSE),
    ('extract',   20, '{audio,video}',   FALSE),
    ('classify',  30, '{audio,video}',   FALSE),
    ('database',  40, '{audio,video}',   TRUE),
    ('rag',       50, '{audio,video}',   TRUE),
    ('wiki',      60, '{audio,video}',   TRUE),
    ('thumbnail', 70, '{audio,video}',   FALSE)
ON CONFLICT (name) DO NOTHING;

-- 16.2 Sources: one row per unique content
CREATE TABLE IF NOT EXISTS alice.sources (
    id          VARCHAR(12)  PRIMARY KEY CHECK (id ~ '^[a-z0-9]{12}$'),
    kind        VARCHAR(10)  NOT NULL CHECK (kind IN ('document', 'image', 'email', 'audio', 'video')),
    hash        VARCHAR(128) NOT NULL,
    size        BIGINT,
    modified    TIMESTAMPTZ,
    captured    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    title       TEXT         NOT NULL,
    path        TEXT         NOT NULL,           -- markdown path relative to the repo root
    blob        VARCHAR(64),                     -- git blob id of the content last written/accepted by the pipeline
    repo_error  TEXT,                            -- set while the markdown is locked (invalid hand edit)
    repo_error_at TIMESTAMPTZ,
    deleted     BOOLEAN      NOT NULL DEFAULT FALSE,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_hash ON alice.sources(hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_path ON alice.sources(path);
CREATE INDEX IF NOT EXISTS idx_sources_repo_error ON alice.sources(id) WHERE repo_error IS NOT NULL;

DROP TRIGGER IF EXISTS trg_sources_updated_at ON alice.sources;
CREATE TRIGGER trg_sources_updated_at
    BEFORE UPDATE ON alice.sources
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

-- 16.3 Locations: NAS path or mailbox + message id
CREATE TABLE IF NOT EXISTS alice.source_locations (
    id          BIGSERIAL    PRIMARY KEY,
    source_id   VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    path        TEXT,
    mailbox     TEXT,
    message_id  TEXT,
    present     BOOLEAN      NOT NULL DEFAULT TRUE,
    first_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    gone_at     TIMESTAMPTZ,
    CHECK ((path IS NOT NULL AND mailbox IS NULL AND message_id IS NULL)
        OR (path IS NULL AND mailbox IS NOT NULL AND message_id IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_source_locations_key
    ON alice.source_locations(source_id, COALESCE(path, ''), COALESCE(mailbox, ''), COALESCE(message_id, ''));
CREATE INDEX IF NOT EXISTS idx_source_locations_path ON alice.source_locations(path) WHERE path IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_locations_mail ON alice.source_locations(mailbox, message_id) WHERE mailbox IS NOT NULL;

-- 16.4 Parents: attachment -> mail
CREATE TABLE IF NOT EXISTS alice.source_parents (
    source_id   VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    parent_id   VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, parent_id),
    CHECK (source_id <> parent_id)
);

CREATE INDEX IF NOT EXISTS idx_source_parents_parent ON alice.source_parents(parent_id);

-- 16.5 Stage state per source
CREATE TABLE IF NOT EXISTS alice.source_stages (
    source_id       VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    stage           VARCHAR(40)  NOT NULL REFERENCES alice.pipeline_stages(name) ON DELETE CASCADE,
    state           VARCHAR(20)  NOT NULL DEFAULT 'pending'
                    CHECK (state IN ('pending', 'running', 'done', 'failed', 'failed_permanent', 'skipped')),
    attempts        INTEGER      NOT NULL DEFAULT 0,
    last_error      TEXT,
    last_attempt_at TIMESTAMPTZ,
    next_retry_at   TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    claim_token     UUID,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_source_stages_due
    ON alice.source_stages(stage, state, next_retry_at) WHERE state IN ('pending', 'failed');
CREATE INDEX IF NOT EXISTS idx_source_stages_running
    ON alice.source_stages(started_at) WHERE state = 'running';

DROP TRIGGER IF EXISTS trg_source_stages_updated_at ON alice.source_stages;
CREATE TRIGGER trg_source_stages_updated_at
    BEFORE UPDATE ON alice.source_stages
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

-- 16.6 Events per source (hand corrections, restores, locks) for later views (PROJ-122)
CREATE TABLE IF NOT EXISTS alice.source_events (
    id          BIGSERIAL    PRIMARY KEY,
    source_id   VARCHAR(12)  REFERENCES alice.sources(id) ON DELETE CASCADE,
    level       VARCHAR(10)  NOT NULL DEFAULT 'info' CHECK (level IN ('info', 'warning', 'error')),
    event       VARCHAR(40)  NOT NULL,
    message     TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_events_source ON alice.source_events(source_id, created_at DESC);

-- 16.7 RLS: only the service database user writes these tables
ALTER TABLE alice.pipeline_stages ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.source_locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.source_parents ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.source_stages ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.source_events ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['pipeline_stages', 'sources', 'source_locations', 'source_parents',
                             'source_stages', 'source_events'] LOOP
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
