-- PROJ-123: Mail import into the ETL (alice-mail-import; register extension). Idempotent.
BEGIN;

-- ============================================================
-- 20. MAIL IMPORT (PROJ-123)
-- ============================================================
-- Working state of alice-mail-import: IMAP mailboxes (alice.imap_mailboxes) ->
-- mail archive (.eml + attachment files on the NAS) -> sources of kind `email` in
-- the register (section 16). Written only by alice-mail-import.

-- 20.1 Register: a mail location is mailbox + folder + UID + message id. The folder
-- belongs to the identity of a location, the UID does not (it changes with UIDVALIDITY).
ALTER TABLE alice.source_locations ADD COLUMN IF NOT EXISTS folder TEXT;
ALTER TABLE alice.source_locations ADD COLUMN IF NOT EXISTS uid BIGINT;
DROP INDEX IF EXISTS alice.idx_source_locations_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_locations_key_folder
    ON alice.source_locations(source_id, COALESCE(path, ''), COALESCE(mailbox, ''), COALESCE(folder, ''),
                              COALESCE(message_id, ''));
CREATE INDEX IF NOT EXISTS idx_source_locations_mail_folder
    ON alice.source_locations(mailbox, folder, uid) WHERE mailbox IS NOT NULL AND present;

-- 20.2 Stage `database` does not apply to mails (no business tables for mails yet)
UPDATE alice.pipeline_stages SET skip_kinds = array_append(skip_kinds, 'email')
 WHERE name = 'database' AND NOT ('email' = ANY(skip_kinds));
UPDATE alice.source_stages ss SET state = 'skipped', attempts = 0, last_error = NULL, next_retry_at = NULL,
       claim_token = NULL, started_at = NULL
  FROM alice.sources s
 WHERE s.id = ss.source_id AND s.kind = 'email' AND ss.stage = 'database' AND ss.state <> 'skipped';

-- 20.3 Mailboxes known to the import: stable archive key (file-name safe, survives a
-- renamed display name). The row stays when the mailbox is deleted in the settings;
-- the nightly run then removes its locations.
CREATE TABLE IF NOT EXISTS alice.mail_import_mailboxes (
    mailbox_id        UUID         PRIMARY KEY,                  -- alice.imap_mailboxes.id (no FK on purpose)
    archive_key       TEXT         NOT NULL UNIQUE CHECK (archive_key ~ '^[a-z0-9][a-z0-9-]{0,80}$'),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_nightly_at   TIMESTAMPTZ,
    removed_at        TIMESTAMPTZ                                -- all locations removed after deletion
);

-- 20.4 Folder state per mailbox (INBOX / sent folder)
CREATE TABLE IF NOT EXISTS alice.mail_import_folders (
    mailbox_id    UUID         NOT NULL REFERENCES alice.mail_import_mailboxes(mailbox_id) ON DELETE CASCADE,
    folder        TEXT         NOT NULL,
    role          VARCHAR(10)  NOT NULL CHECK (role IN ('inbox', 'sent')),
    uidvalidity   BIGINT,
    baseline_uid  BIGINT,                                         -- UIDNEXT at the first import (no start date)
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (mailbox_id, folder)
);

-- 20.5 Archive entry per mail source
CREATE TABLE IF NOT EXISTS alice.mail_archive (
    source_id     VARCHAR(12)  PRIMARY KEY REFERENCES alice.sources(id) ON DELETE CASCADE,
    archive_key   TEXT         NOT NULL,
    eml_path      TEXT         NOT NULL,                          -- relative to the archive root
    attachments   JSONB        NOT NULL DEFAULT '[]',             -- [{filename, mime_type, size, path}]
    broken        TEXT,                                           -- cause if the MIME structure is broken
    size          BIGINT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mail_archive_key ON alice.mail_archive(archive_key);

-- 20.6 Nightly runs with their summary (removed / deleted / fetched / blocked per mailbox)
CREATE TABLE IF NOT EXISTS alice.mail_import_runs (
    id           BIGSERIAL    PRIMARY KEY,
    kind         VARCHAR(10)  NOT NULL DEFAULT 'nightly' CHECK (kind IN ('nightly', 'manual')),
    state        VARCHAR(10)  NOT NULL DEFAULT 'running' CHECK (state IN ('running', 'done', 'failed')),
    started_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    summary      JSONB
);

CREATE INDEX IF NOT EXISTS idx_mail_import_runs_started ON alice.mail_import_runs(kind, started_at DESC);

-- 20.7 RLS: only the service database user writes these tables
ALTER TABLE alice.mail_import_mailboxes ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.mail_import_folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.mail_archive ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.mail_import_runs ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['mail_import_mailboxes', 'mail_import_folders', 'mail_archive', 'mail_import_runs'] LOOP
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
