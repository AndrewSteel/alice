-- PROJ-124: Mail attachments as sources (alice-mail-import). Idempotent.
BEGIN;

-- ============================================================
-- 21. MAIL ATTACHMENTS AS SOURCES (PROJ-124)
-- ============================================================
-- The real attachments of imported mails (mail archive, section 20) become sources of their
-- own in the register (section 16), with the mails as `parents`. Written only by alice-mail-import.

-- 21.1 State per mail: last complete registration (compared with the end of `extract`), pause
-- while the archive is not readable, state of the references in the mail markdown
CREATE TABLE IF NOT EXISTS alice.mail_attachment_mails (
    mail_id         VARCHAR(12)  PRIMARY KEY REFERENCES alice.sources(id) ON DELETE CASCADE,
    processed_at    TIMESTAMPTZ,                       -- all attachments registered (NULL: not yet)
    next_try_at     TIMESTAMPTZ,                       -- paused (archive file not readable) until
    pause_reason    TEXT,
    links_ok        BOOLEAN      NOT NULL DEFAULT FALSE,
    link_error      TEXT,
    link_attempts   INTEGER      NOT NULL DEFAULT 0,
    link_retry_at   TIMESTAMPTZ,
    mail_path       TEXT,                              -- mail markdown path the links were built for
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mail_attachment_mails_links
    ON alice.mail_attachment_mails(link_retry_at) WHERE NOT links_ok;

-- 21.2 One row per attachment of a mail (position in `attachments`)
CREATE TABLE IF NOT EXISTS alice.mail_attachments (
    mail_id         VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    position        INTEGER      NOT NULL,
    filename        TEXT         NOT NULL,
    path            TEXT         NOT NULL,             -- relative to the archive root
    extension       TEXT         NOT NULL DEFAULT '',
    size            BIGINT,
    mtime_ns        BIGINT,
    hash            TEXT,
    status          VARCHAR(12)  NOT NULL CHECK (status IN ('registered', 'unsupported', 'empty')),
    source_id       VARCHAR(12)  REFERENCES alice.sources(id) ON DELETE SET NULL,
    linked_path     TEXT,                              -- attachment markdown path used in the mail link
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (mail_id, position)
);

CREATE INDEX IF NOT EXISTS idx_mail_attachments_source ON alice.mail_attachments(source_id);
CREATE INDEX IF NOT EXISTS idx_mail_attachments_status ON alice.mail_attachments(status, extension);

-- 21.3 Summaries "attachments not processed" per run (tick / reconciliation), for PROJ-122
CREATE TABLE IF NOT EXISTS alice.mail_attachment_runs (
    id           BIGSERIAL    PRIMARY KEY,
    kind         VARCHAR(10)  NOT NULL CHECK (kind IN ('tick', 'reconcile')),
    started_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    summary      JSONB        NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_mail_attachment_runs_started ON alice.mail_attachment_runs(started_at DESC);

-- 21.4 RLS: only the service database user writes these tables
ALTER TABLE alice.mail_attachment_mails ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.mail_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.mail_attachment_runs ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['mail_attachment_mails', 'mail_attachments', 'mail_attachment_runs'] LOOP
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
