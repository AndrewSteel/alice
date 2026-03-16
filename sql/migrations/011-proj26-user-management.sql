-- ============================================================
-- Migration 011: PROJ-26 Admin User Management
-- ============================================================
-- Adds must_change_password column (for fresh installs it is
-- already defined in init-postgres.sql; this migration makes
-- the column available on existing deployments).
-- Also removes the never-used last_login column (duplicate of
-- last_login_at which was added in migration 007) and adds a
-- UNIQUE constraint on alice.users.email.
-- ============================================================

-- 1. Add must_change_password if not present (idempotent)
ALTER TABLE alice.users
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Remove the unused last_login column (added in original schema,
--    superseded by last_login_at from migration 007)
ALTER TABLE alice.users
    DROP COLUMN IF EXISTS last_login;

-- 3. Add UNIQUE index on email (partial: only for non-NULL values,
--    since existing users without email should not conflict)
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
    ON alice.users (email)
    WHERE email IS NOT NULL;
