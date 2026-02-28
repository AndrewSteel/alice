-- ============================================================
-- Migration 007: Ensure auth columns exist on alice.users
-- ============================================================
-- Idempotent: safe to run multiple times.
-- The base schema (init-postgres.sql) already defines these
-- columns; this migration ensures they exist when upgrading
-- an existing database that pre-dates Phase 1.5.
-- ============================================================

-- password_hash: bcrypt hash of the user's password (cost 12)
ALTER TABLE alice.users
    ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);

-- is_active: false = account disabled, cannot log in
ALTER TABLE alice.users
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

-- last_login_at: timestamp of last successful login
ALTER TABLE alice.users
    ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

-- failed_login_attempts: reserved for future rate-limiting (Phase 3)
ALTER TABLE alice.users
    ADD COLUMN IF NOT EXISTS failed_login_attempts INT NOT NULL DEFAULT 0;

-- locked_until: reserved for future account locking (Phase 3)
ALTER TABLE alice.users
    ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;
