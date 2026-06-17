-- Migration 015: Extend sessions.source to allow device-specific ESPHome values
-- Replaces the strict IN-check with one that also accepts 'esphome:<room>' patterns.

ALTER TABLE alice.sessions
    DROP CONSTRAINT IF EXISTS sessions_source_check;

ALTER TABLE alice.sessions
    ADD CONSTRAINT sessions_source_check
    CHECK (source IS NULL OR source IN ('webapp_cc', 'webapp_mic', 'esphome') OR source LIKE 'esphome:%');
