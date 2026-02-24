-- ============================================================
-- ALICE - HA Intent Infrastructure
-- PROJ-1: HA Intent Infrastructure (DB-Schema & Weaviate Collection)
-- ============================================================
-- Extends the alice schema with tables for HA intent recognition.
-- Safe to re-run: uses CREATE TABLE IF NOT EXISTS throughout.
-- ============================================================

-- ============================================================
-- 1. ha_intent_templates
-- Purpose: Stores the "vocabulary" of HA commands.
--          One row = one intent type (e.g. "turn on lights in room X")
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.ha_intent_templates (
    id              SERIAL PRIMARY KEY,
    domain          VARCHAR(50)  NOT NULL,           -- e.g. light, switch, climate
    intent          VARCHAR(100) NOT NULL,            -- e.g. turn_on, turn_off, set_temperature
    service         VARCHAR(100) NOT NULL,            -- HA service, e.g. light.turn_on
    patterns        JSONB        NOT NULL DEFAULT '[]', -- Array of pattern strings with {name}/{area}/{where}
    default_parameters JSONB     NOT NULL DEFAULT '{}', -- Default service call parameters
    requires_confirmation BOOLEAN NOT NULL DEFAULT FALSE, -- TRUE for safety-critical domains
    language        VARCHAR(10)  NOT NULL DEFAULT 'de',
    priority        SMALLINT     NOT NULL DEFAULT 50, -- Higher = preferred in ambiguous matches
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    source          VARCHAR(50)  NOT NULL DEFAULT 'seed', -- seed | user | auto
    notes           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_ha_intent_templates_domain
    ON alice.ha_intent_templates (domain);

CREATE INDEX IF NOT EXISTS idx_ha_intent_templates_is_active
    ON alice.ha_intent_templates (is_active);

CREATE INDEX IF NOT EXISTS idx_ha_intent_templates_domain_active
    ON alice.ha_intent_templates (domain, is_active)
    WHERE is_active = TRUE;

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION alice.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ha_intent_templates_updated_at ON alice.ha_intent_templates;
CREATE TRIGGER trg_ha_intent_templates_updated_at
    BEFORE UPDATE ON alice.ha_intent_templates
    FOR EACH ROW EXECUTE FUNCTION alice.update_updated_at_column();

-- Row Level Security
ALTER TABLE alice.ha_intent_templates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ha_intent_templates_select ON alice.ha_intent_templates;
CREATE POLICY ha_intent_templates_select ON alice.ha_intent_templates
    FOR SELECT USING (TRUE);

DROP POLICY IF EXISTS ha_intent_templates_insert ON alice.ha_intent_templates;
CREATE POLICY ha_intent_templates_insert ON alice.ha_intent_templates
    FOR INSERT WITH CHECK (TRUE);

DROP POLICY IF EXISTS ha_intent_templates_update ON alice.ha_intent_templates;
CREATE POLICY ha_intent_templates_update ON alice.ha_intent_templates
    FOR UPDATE USING (TRUE);

DROP POLICY IF EXISTS ha_intent_templates_delete ON alice.ha_intent_templates;
CREATE POLICY ha_intent_templates_delete ON alice.ha_intent_templates
    FOR DELETE USING (TRUE);


-- ============================================================
-- 2. ha_entities
-- Purpose: Mirror of the current HA entity registry.
--          One row = one HA device/sensor.
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.ha_entities (
    id              SERIAL PRIMARY KEY,
    entity_id       VARCHAR(255) NOT NULL UNIQUE,    -- e.g. light.wohnzimmer_decke
    domain          VARCHAR(50)  NOT NULL,
    friendly_name   VARCHAR(255),
    area_id         VARCHAR(100),
    area_name       VARCHAR(100),
    aliases         JSONB        NOT NULL DEFAULT '[]',
    device_class    VARCHAR(100),
    supported_features INTEGER,
    last_seen_at    TIMESTAMPTZ,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    weaviate_synced BOOLEAN      NOT NULL DEFAULT FALSE,
    intents_count   INT          NOT NULL DEFAULT 0, -- Denormalized: number of HAIntent entries in Weaviate
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_ha_entities_domain
    ON alice.ha_entities (domain);

CREATE INDEX IF NOT EXISTS idx_ha_entities_is_active
    ON alice.ha_entities (is_active);

CREATE INDEX IF NOT EXISTS idx_ha_entities_sync_pending
    ON alice.ha_entities (is_active, weaviate_synced)
    WHERE is_active = TRUE AND weaviate_synced = FALSE;

-- Auto-update updated_at
DROP TRIGGER IF EXISTS trg_ha_entities_updated_at ON alice.ha_entities;
CREATE TRIGGER trg_ha_entities_updated_at
    BEFORE UPDATE ON alice.ha_entities
    FOR EACH ROW EXECUTE FUNCTION alice.update_updated_at_column();

-- Row Level Security
ALTER TABLE alice.ha_entities ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ha_entities_select ON alice.ha_entities;
CREATE POLICY ha_entities_select ON alice.ha_entities
    FOR SELECT USING (TRUE);

DROP POLICY IF EXISTS ha_entities_insert ON alice.ha_entities;
CREATE POLICY ha_entities_insert ON alice.ha_entities
    FOR INSERT WITH CHECK (TRUE);

DROP POLICY IF EXISTS ha_entities_update ON alice.ha_entities;
CREATE POLICY ha_entities_update ON alice.ha_entities
    FOR UPDATE USING (TRUE);

DROP POLICY IF EXISTS ha_entities_delete ON alice.ha_entities;
CREATE POLICY ha_entities_delete ON alice.ha_entities
    FOR DELETE USING (TRUE);


-- ============================================================
-- 3. ha_sync_log
-- Purpose: Audit trail for every HA sync run.
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.ha_sync_log (
    id                  SERIAL PRIMARY KEY,
    sync_type           VARCHAR(50)  NOT NULL,   -- full | incremental | manual
    trigger_source      VARCHAR(50)  NOT NULL,   -- mqtt | schedule | manual | startup
    entities_found      INT          NOT NULL DEFAULT 0,
    entities_added      INT          NOT NULL DEFAULT 0,
    entities_removed    INT          NOT NULL DEFAULT 0,
    entities_updated    INT          NOT NULL DEFAULT 0,
    intents_generated   INT          NOT NULL DEFAULT 0,
    intents_removed     INT          NOT NULL DEFAULT 0,
    duration_ms         INT,
    status              VARCHAR(20)  NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running', 'success', 'partial', 'error')),
    error_message       TEXT,
    details             JSONB        NOT NULL DEFAULT '{}',
    started_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_ha_sync_log_started_at
    ON alice.ha_sync_log (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ha_sync_log_sync_type
    ON alice.ha_sync_log (sync_type);

-- Row Level Security
ALTER TABLE alice.ha_sync_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ha_sync_log_select ON alice.ha_sync_log;
CREATE POLICY ha_sync_log_select ON alice.ha_sync_log
    FOR SELECT USING (TRUE);

DROP POLICY IF EXISTS ha_sync_log_insert ON alice.ha_sync_log;
CREATE POLICY ha_sync_log_insert ON alice.ha_sync_log
    FOR INSERT WITH CHECK (TRUE);

DROP POLICY IF EXISTS ha_sync_log_update ON alice.ha_sync_log;
CREATE POLICY ha_sync_log_update ON alice.ha_sync_log
    FOR UPDATE USING (TRUE);

DROP POLICY IF EXISTS ha_sync_log_delete ON alice.ha_sync_log;
CREATE POLICY ha_sync_log_delete ON alice.ha_sync_log
    FOR DELETE USING (TRUE);


-- ============================================================
-- 4. SEED DATA: Intent Templates
-- 19 templates covering 8 HA domains (German, language='de')
-- Uses ON CONFLICT DO NOTHING for idempotency.
-- ============================================================

-- Unique constraint to enable ON CONFLICT (idempotent for PG 12+)
DO $$ BEGIN
    ALTER TABLE alice.ha_intent_templates
        ADD CONSTRAINT uq_ha_intent_templates_domain_intent_lang
        UNIQUE (domain, intent, language);
EXCEPTION WHEN duplicate_table THEN NULL;
END $$;

INSERT INTO alice.ha_intent_templates
    (domain, intent, service, patterns, default_parameters, requires_confirmation, language, priority, source)
VALUES

-- light
('light', 'turn_on', 'light.turn_on',
 '["Licht {name} einschalten","Licht in der {area} einschalten","{where} Licht an","Schalte {name} ein","Mach das Licht in der {area} an"]',
 '{}', FALSE, 'de', 60, 'seed'),

('light', 'turn_off', 'light.turn_off',
 '["Licht {name} ausschalten","Licht in der {area} ausschalten","{where} Licht aus","Schalte {name} aus","Mach das Licht in der {area} aus"]',
 '{}', FALSE, 'de', 60, 'seed'),

('light', 'set_brightness', 'light.turn_on',
 '["Helligkeit {name} auf {value} Prozent","Dimme {name} auf {value}","Licht in der {area} auf {value} Prozent dimmen"]',
 '{}', FALSE, 'de', 50, 'seed'),

-- switch
('switch', 'turn_on', 'switch.turn_on',
 '["Schalter {name} einschalten","Schalte {name} ein","Mach {name} an"]',
 '{}', FALSE, 'de', 55, 'seed'),

('switch', 'turn_off', 'switch.turn_off',
 '["Schalter {name} ausschalten","Schalte {name} aus","Mach {name} aus"]',
 '{}', FALSE, 'de', 55, 'seed'),

-- climate
('climate', 'set_temperature', 'climate.set_temperature',
 '["Temperatur in der {area} auf {value} Grad","Heizung in der {area} auf {value} Grad stellen","{where} auf {value} Grad einstellen"]',
 '{}', FALSE, 'de', 60, 'seed'),

('climate', 'turn_on', 'climate.turn_on',
 '["Heizung in der {area} einschalten","Heizung {name} an"]',
 '{}', FALSE, 'de', 50, 'seed'),

('climate', 'turn_off', 'climate.turn_off',
 '["Heizung in der {area} ausschalten","Heizung {name} aus"]',
 '{}', FALSE, 'de', 50, 'seed'),

-- cover (Rolladen/Jalousien)
('cover', 'open_cover', 'cover.open_cover',
 '["Rolladen {name} öffnen","Rolladen in der {area} hoch","{name} hochfahren","Jalousie {name} öffnen"]',
 '{}', FALSE, 'de', 55, 'seed'),

('cover', 'close_cover', 'cover.close_cover',
 '["Rolladen {name} schließen","Rolladen in der {area} runter","{name} runterfahren","Jalousie {name} schließen"]',
 '{}', FALSE, 'de', 55, 'seed'),

-- media_player
('media_player', 'turn_on', 'media_player.turn_on',
 '["Fernseher {name} einschalten","{name} an","TV in der {area} einschalten"]',
 '{}', FALSE, 'de', 50, 'seed'),

('media_player', 'turn_off', 'media_player.turn_off',
 '["Fernseher {name} ausschalten","{name} aus","TV in der {area} ausschalten"]',
 '{}', FALSE, 'de', 50, 'seed'),

('media_player', 'volume_set', 'media_player.volume_set',
 '["Lautstärke {name} auf {value}","Lautstärke am {name} auf {value} Prozent stellen"]',
 '{}', FALSE, 'de', 45, 'seed'),

-- vacuum
('vacuum', 'start', 'vacuum.start',
 '["Staubsauger {name} starten","Saugroboter {name} losschicken","{name} saugen lassen"]',
 '{}', FALSE, 'de', 55, 'seed'),

('vacuum', 'return_to_base', 'vacuum.return_to_base',
 '["Staubsauger {name} zurückschicken","{name} zur Ladestation"]',
 '{}', FALSE, 'de', 55, 'seed'),

-- lock (requires_confirmation = TRUE)
('lock', 'lock', 'lock.lock',
 '["Schloss {name} sperren","{name} abschließen","Tür {name} sperren"]',
 '{}', TRUE, 'de', 70, 'seed'),

('lock', 'unlock', 'lock.unlock',
 '["Schloss {name} öffnen","{name} aufschließen","Tür {name} öffnen"]',
 '{}', TRUE, 'de', 70, 'seed'),

-- alarm_control_panel (requires_confirmation = TRUE)
('alarm_control_panel', 'alarm_arm_away', 'alarm_control_panel.alarm_arm_away',
 '["Alarm aktivieren","Alarmanlage scharf schalten","Haus sichern"]',
 '{}', TRUE, 'de', 80, 'seed'),

('alarm_control_panel', 'alarm_disarm', 'alarm_control_panel.alarm_disarm',
 '["Alarm deaktivieren","Alarmanlage deaktivieren","Alarm aus"]',
 '{}', TRUE, 'de', 80, 'seed')

ON CONFLICT (domain, intent, language) DO NOTHING;
