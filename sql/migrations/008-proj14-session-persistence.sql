-- ============================================================
-- PROJ-14: Session Persistence — Schema Migration
-- Tables alice.sessions and alice.messages are empty before this runs.
-- Run: docker exec postgres psql -U user -d alice -f /path/to/008-proj14-session-persistence.sql
-- ============================================================

BEGIN;

-- Drop indexes that reference user_id before altering column types
DROP INDEX IF EXISTS alice.idx_messages_user_recent;
DROP INDEX IF EXISTS alice.idx_messages_not_transferred;

-- ============================================================
-- 1. alice.sessions — fix user_id type, add title, add FK
-- ============================================================

-- user_id: VARCHAR(255) → UUID referencing alice.users
ALTER TABLE alice.sessions
  ALTER COLUMN user_id TYPE UUID USING user_id::UUID;

ALTER TABLE alice.sessions
  ADD CONSTRAINT fk_sessions_user
  FOREIGN KEY (user_id) REFERENCES alice.users(id) ON DELETE CASCADE;

-- title: new column for chat session display name
ALTER TABLE alice.sessions
  ADD COLUMN IF NOT EXISTS title VARCHAR(255);

-- ============================================================
-- 2. alice.messages — fix user_id type, add FKs
-- ============================================================

-- user_id: VARCHAR(255) → UUID referencing alice.users
ALTER TABLE alice.messages
  ALTER COLUMN user_id TYPE UUID USING user_id::UUID;

ALTER TABLE alice.messages
  ADD CONSTRAINT fk_messages_user
  FOREIGN KEY (user_id) REFERENCES alice.users(id) ON DELETE CASCADE;

-- session_id FK with CASCADE: deleting a session removes all its messages
ALTER TABLE alice.messages
  ADD CONSTRAINT fk_messages_session
  FOREIGN KEY (session_id) REFERENCES alice.sessions(session_id) ON DELETE CASCADE;

-- ============================================================
-- 3. Recreate indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_sessions_user
  ON alice.sessions(user_id, last_activity DESC);

CREATE INDEX IF NOT EXISTS idx_messages_user_recent
  ON alice.messages(user_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_messages_not_transferred
  ON alice.messages(user_id)
  WHERE transferred_to_weaviate = FALSE;

-- ============================================================
-- 4. Enable Row Level Security (defense-in-depth)
--    The n8n service account (table owner) bypasses RLS.
--    These permissive policies ensure any non-owner role is
--    explicitly covered and RLS is active on both tables.
-- ============================================================

ALTER TABLE alice.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY sessions_allow_all ON alice.sessions
  FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY messages_allow_all ON alice.messages
  FOR ALL USING (true) WITH CHECK (true);

COMMIT;
