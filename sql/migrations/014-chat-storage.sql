-- Migration 014: Chat Storage & Title Generation (PROJ-51)
-- Safe to re-run (uses ADD COLUMN IF NOT EXISTS).

ALTER TABLE alice.sessions
    ADD COLUMN IF NOT EXISTS session_type TEXT NOT NULL DEFAULT 'llm'
        CHECK (session_type IN ('llm', 'ha_only')),
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source TEXT
        CHECK (source IN ('webapp_cc', 'webapp_mic', 'esphome'));

ALTER TABLE alice.messages
    ADD COLUMN IF NOT EXISTS msg_type TEXT
        CHECK (msg_type IN ('user_text', 'user_stt', 'llm_thinking', 'llm_response', 'ha_result', 'tool_result'));

CREATE INDEX IF NOT EXISTS idx_sessions_cleanup
    ON alice.sessions(session_type, expires_at)
    WHERE session_type = 'ha_only' AND expires_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_messages_msg_type
    ON alice.messages(session_id, msg_type);
