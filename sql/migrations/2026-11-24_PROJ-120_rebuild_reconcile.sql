-- PROJ-120: Rebuild + completeness reconciliation (alice-etl-rebuild; register and detection extensions). Idempotent.
BEGIN;

-- ============================================================
-- 19. REBUILD + COMPLETENESS RECONCILIATION (PROJ-120)
-- ============================================================
-- Rebuild runs (stages back to pending in throttled portions, worked off by the
-- existing stage services) and the nightly / on-demand reconciliation
-- NAS <-> register <-> repo <-> stages <-> DB. Runs, items and results are written
-- by alice-etl-rebuild; the register (section 16) and the detection (section 17)
-- get a few columns/tables of their own.

-- 19.1 Register: a stage set to pending by a rebuild run carries the run id. Such work
-- is claimed after normal work and its markdown writes go into batch commits.
-- Normal resets (content change, hand correction, retry) clear it.
ALTER TABLE alice.source_stages ADD COLUMN IF NOT EXISTS rebuild_run BIGINT;

-- 19.2 Register: stages that a stage service has actually served for a kind
-- (first claim of a source of that kind). Only served stages belong to a rebuild
-- and to the stage check of the reconciliation.
CREATE TABLE IF NOT EXISTS alice.pipeline_stage_served (
    stage            VARCHAR(40)  NOT NULL REFERENCES alice.pipeline_stages(name) ON DELETE CASCADE,
    kind             VARCHAR(10)  NOT NULL,
    first_served_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stage, kind)
);

-- Existing installations: every stage/kind that already ran once counts as served.
INSERT INTO alice.pipeline_stage_served (stage, kind)
SELECT DISTINCT ss.stage, s.kind
  FROM alice.source_stages ss JOIN alice.sources s ON s.id = ss.source_id
 WHERE ss.state IN ('done', 'running', 'failed', 'failed_permanent')
ON CONFLICT DO NOTHING;

-- 19.3 Detection: rolling re-hash of the originals (one cycle = every known path once)
ALTER TABLE alice.detect_files ADD COLUMN IF NOT EXISTS rehashed_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_detect_files_rehashed ON alice.detect_files(rehashed_at NULLS FIRST, path);

CREATE TABLE IF NOT EXISTS alice.detect_hash_cycle (
    id          INTEGER      PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    started_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 19.4 Rebuild runs
CREATE TABLE IF NOT EXISTS alice.rebuild_runs (
    id            BIGSERIAL    PRIMARY KEY,
    start_stage   VARCHAR(40)  NOT NULL,
    kind          VARCHAR(10),                                  -- NULL = all kinds
    scope         JSONB        NOT NULL DEFAULT '{}',           -- {kind: {stages: [...], not_served: [...]}}
    state         VARCHAR(10)  NOT NULL DEFAULT 'running'
                  CHECK (state IN ('running', 'paused', 'waiting', 'done', 'cancelled')),
    reason        TEXT,                                         -- why it is waiting
    started_by    TEXT         NOT NULL,
    started_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ,
    total         INTEGER      NOT NULL DEFAULT 0,
    final_counts  JSONB,                                        -- progress at the end
    reconcile_id  BIGINT
);

CREATE INDEX IF NOT EXISTS idx_rebuild_runs_state ON alice.rebuild_runs(state);
CREATE INDEX IF NOT EXISTS idx_rebuild_runs_started ON alice.rebuild_runs(started_at DESC);

-- 19.5 Sources of a run (snapshot at the start)
CREATE TABLE IF NOT EXISTS alice.rebuild_items (
    run_id       BIGINT       NOT NULL REFERENCES alice.rebuild_runs(id) ON DELETE CASCADE,
    source_id    VARCHAR(12)  NOT NULL,
    kind         VARCHAR(10)  NOT NULL,
    seq          INTEGER      NOT NULL,                         -- release order
    excluded     VARCHAR(20)  CHECK (excluded IN ('deleted', 'locked', 'skipped', 'not_served')),
    released_at  TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,                                   -- all stages through (throughput)
    PRIMARY KEY (run_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_rebuild_items_open ON alice.rebuild_items(run_id, seq)
    WHERE released_at IS NULL AND excluded IS NULL;
CREATE INDEX IF NOT EXISTS idx_rebuild_items_released ON alice.rebuild_items(run_id)
    WHERE released_at IS NOT NULL AND excluded IS NULL;
CREATE INDEX IF NOT EXISTS idx_rebuild_items_finished ON alice.rebuild_items(run_id, finished_at);
CREATE INDEX IF NOT EXISTS idx_rebuild_items_source ON alice.rebuild_items(source_id);

-- 19.6 Reconciliation results and their gaps
CREATE TABLE IF NOT EXISTS alice.reconcile_results (
    id               BIGSERIAL    PRIMARY KEY,
    kind             VARCHAR(15)  NOT NULL CHECK (kind IN ('nightly', 'on_demand', 'after_rebuild')),
    mode             VARCHAR(15)  NOT NULL DEFAULT 'levels' CHECK (mode IN ('levels', 'full_rehash')),
    rebuild_run_id   BIGINT       REFERENCES alice.rebuild_runs(id) ON DELETE SET NULL,
    state            VARCHAR(10)  NOT NULL DEFAULT 'running'
                     CHECK (state IN ('running', 'complete', 'incomplete')),
    reason           TEXT,
    guard_triggered  BOOLEAN      NOT NULL DEFAULT FALSE,
    started_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at      TIMESTAMPTZ,
    summary          JSONB        NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_reconcile_results_started ON alice.reconcile_results(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_reconcile_results_run ON alice.reconcile_results(rebuild_run_id);

CREATE TABLE IF NOT EXISTS alice.reconcile_gaps (
    id          BIGSERIAL    PRIMARY KEY,
    result_id   BIGINT       NOT NULL REFERENCES alice.reconcile_results(id) ON DELETE CASCADE,
    level       SMALLINT     NOT NULL CHECK (level BETWEEN 1 AND 9),
    gap         VARCHAR(40)  NOT NULL,
    source_id   VARCHAR(12),
    path        TEXT,
    detail      TEXT,
    action      VARCHAR(15)  NOT NULL CHECK (action IN ('repaired', 'reported', 'repair_failed'))
);

CREATE INDEX IF NOT EXISTS idx_reconcile_gaps_result ON alice.reconcile_gaps(result_id, level, id);

-- 19.7 RLS: only the service database users write these tables
ALTER TABLE alice.pipeline_stage_served ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.detect_hash_cycle ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.rebuild_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.rebuild_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.reconcile_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.reconcile_gaps ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['pipeline_stage_served', 'detect_hash_cycle', 'rebuild_runs', 'rebuild_items',
                             'reconcile_results', 'reconcile_gaps'] LOOP
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
