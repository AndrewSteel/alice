-- ============================================================
-- Migration 073 — PROJ-85 Refinement 2026-10-15: house-wide timer alarm.
--
-- Adds:
--   1. alice.timers.acknowledged_by — who ended the alarm: 'voice' (a Voice PE
--      was addressed), 'webapp' (the toast was closed) or 'timeout' (nobody
--      reacted within the max melody time / nothing could be delivered).
--      The WebApp catch-up message is only shown for timers nobody actively
--      acknowledged (still 'expired', or acknowledged_by = 'timeout').
--   2. One-time cleanup: every timer still stuck in 'expired' — notably all
--      WebApp-set ones, which were never acknowledged before — becomes
--      'acknowledged' / 'timeout'. Without it the first "Hey Jarvis" after the
--      deploy would announce all of them, since the announcement no longer
--      filters by device.
--
-- Apply against the alice database after 072-proj106-lists.sql.
-- Safe to re-run (ADD COLUMN IF NOT EXISTS; the cleanup only touches rows
-- still in 'expired', which at deploy time are leftovers by definition).
-- ============================================================

ALTER TABLE alice.timers
    ADD COLUMN IF NOT EXISTS acknowledged_by VARCHAR(16)
        CHECK (acknowledged_by IN ('voice', 'webapp', 'timeout'));

COMMENT ON COLUMN alice.timers.acknowledged_by IS
    'Who ended the expiry alarm: voice | webapp | timeout. NULL while not acknowledged (or acknowledged before migration 073).';

UPDATE alice.timers
   SET status = 'acknowledged', acknowledged_by = 'timeout', updated_at = NOW()
 WHERE status = 'expired';

-- The announcement claim and the WebApp catch-up list filter expired /
-- recently acknowledged rows by fired_at.
CREATE INDEX IF NOT EXISTS idx_timers_fired_at
    ON alice.timers (fired_at)
    WHERE status IN ('expired', 'acknowledged');
