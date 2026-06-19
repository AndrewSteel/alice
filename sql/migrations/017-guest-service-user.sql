-- Migration 017 — PROJ-43 bugfix: seed the Wyoming guest service user
--
-- wyoming_transport._token_for() mints a service JWT with
-- user_id = '00000000-0000-0000-0000-000000000000' for unidentified speakers.
-- alice-chat-stream's ensure_session() inserts into alice.sessions which has a
-- FK on alice.users(id) — without this row the insert fails with a FK violation
-- and alice-chat-stream returns 503 for every Wyoming voice turn.
--
-- Safe to re-run (ON CONFLICT DO NOTHING).
-- Requires migration-016 (allow_voice_enrollment column) to be applied first.

BEGIN;

INSERT INTO alice.users (
    id,
    username,
    display_name,
    role,
    is_active,
    must_change_password,
    allow_voice_enrollment
)
VALUES (
    '00000000-0000-0000-0000-000000000000',
    'voice-guest',
    'Gast (Sprachsteuerung)',
    'guest',
    true,
    false,
    false
)
ON CONFLICT (id) DO NOTHING;

-- Initialise permissions from the 'guest' role template so the user can
-- trigger HA commands (lights, etc.) as a guest.
SELECT alice.init_user_permissions('00000000-0000-0000-0000-000000000000', 'guest');

COMMIT;
