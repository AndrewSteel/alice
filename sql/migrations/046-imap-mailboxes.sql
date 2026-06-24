-- Migration: PROJ-46 Mail IMAP Integration
-- Creates tables for IMAP mailbox configuration and per-user access control.

-- ============================================================
-- IMAP MAILBOXES
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.imap_mailboxes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    display_name    VARCHAR(255) NOT NULL,
    imap_host       VARCHAR(255) NOT NULL,
    imap_port       INTEGER NOT NULL DEFAULT 993,
    imap_username   VARCHAR(255) NOT NULL,
    password_enc    TEXT NOT NULL,       -- AES-256-CBC encrypted, base64url, handled by n8n
    ssl_enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    sync_interval   INTEGER NOT NULL DEFAULT 15,  -- minutes between syncs
    start_date      DATE,               -- backfill emails from this date; NULL = only new emails
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'syncing', 'error', 'unclassified')),
    mails_indexed   INTEGER NOT NULL DEFAULT 0,
    last_synced_at  TIMESTAMPTZ,
    last_uid        BIGINT NOT NULL DEFAULT 0,   -- highest IMAP UID successfully fetched
    last_error      TEXT,
    next_sync_at    TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE alice.imap_mailboxes ENABLE ROW LEVEL SECURITY;

CREATE POLICY imap_mailboxes_select ON alice.imap_mailboxes FOR SELECT USING (TRUE);
CREATE POLICY imap_mailboxes_insert ON alice.imap_mailboxes FOR INSERT WITH CHECK (TRUE);
CREATE POLICY imap_mailboxes_update ON alice.imap_mailboxes FOR UPDATE USING (TRUE);
CREATE POLICY imap_mailboxes_delete ON alice.imap_mailboxes FOR DELETE USING (TRUE);

CREATE INDEX IF NOT EXISTS idx_imap_mailboxes_owner     ON alice.imap_mailboxes(owner_id);
CREATE INDEX IF NOT EXISTS idx_imap_mailboxes_next_sync ON alice.imap_mailboxes(next_sync_at);
CREATE INDEX IF NOT EXISTS idx_imap_mailboxes_status    ON alice.imap_mailboxes(status);

CREATE OR REPLACE TRIGGER set_updated_at_imap_mailboxes
    BEFORE UPDATE ON alice.imap_mailboxes
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

-- ============================================================
-- IMAP MAILBOX ACCESS
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.imap_mailbox_access (
    mailbox_id  UUID NOT NULL REFERENCES alice.imap_mailboxes(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    granted_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (mailbox_id, user_id)
);

ALTER TABLE alice.imap_mailbox_access ENABLE ROW LEVEL SECURITY;

CREATE POLICY imap_access_select ON alice.imap_mailbox_access FOR SELECT USING (TRUE);
CREATE POLICY imap_access_insert ON alice.imap_mailbox_access FOR INSERT WITH CHECK (TRUE);
CREATE POLICY imap_access_update ON alice.imap_mailbox_access FOR UPDATE USING (TRUE);
CREATE POLICY imap_access_delete ON alice.imap_mailbox_access FOR DELETE USING (TRUE);

CREATE INDEX IF NOT EXISTS idx_imap_access_mailbox ON alice.imap_mailbox_access(mailbox_id);
CREATE INDEX IF NOT EXISTS idx_imap_access_user    ON alice.imap_mailbox_access(user_id);
