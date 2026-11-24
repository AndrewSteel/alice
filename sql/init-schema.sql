-- ============================================================
-- ALICE — Consolidated Database Schema
-- Complete current schema: a fresh database needs only this file.
--
-- Safe to re-run (uses IF NOT EXISTS), but it does not add columns
-- to tables that already exist.
-- seed-users.sql must be run separately (not in git).
-- ============================================================

CREATE SCHEMA IF NOT EXISTS alice;

-- ============================================================
-- SHARED TRIGGER FUNCTION
-- ============================================================

CREATE OR REPLACE FUNCTION alice.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 1. USERS
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.users (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username                    VARCHAR(50) UNIQUE NOT NULL,
    display_name                VARCHAR(100),
    email                       VARCHAR(255),

    -- Auth
    password_hash               VARCHAR(255),
    must_change_password        BOOLEAN NOT NULL DEFAULT FALSE,

    -- Phase 2: WebAuthn/Passkeys
    webauthn_credentials        JSONB DEFAULT '[]',

    -- Phase 2: Speaker Recognition
    speaker_embeddings          JSONB DEFAULT '[]',
    speaker_enrollment_complete BOOLEAN DEFAULT FALSE,

    role                        VARCHAR(20) DEFAULT 'haushalt'
                                    CHECK (role IN ('admin', 'haushalt', 'guest')),
    is_active                   BOOLEAN DEFAULT TRUE,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    last_login_at               TIMESTAMPTZ,
    failed_login_attempts       INT DEFAULT 0,
    locked_until                TIMESTAMPTZ,

    -- Admin-only toggle: shows the voice enrollment button on the user's profile page
    allow_voice_enrollment      BOOLEAN DEFAULT false
);

-- Partial unique index: NULL emails do not conflict
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
    ON alice.users (email)
    WHERE email IS NOT NULL;

-- Index: fast lookup of enrolled users on every Wyoming turn.
CREATE INDEX IF NOT EXISTS idx_users_speaker_enrolled
    ON alice.users (speaker_enrollment_complete, is_active)
    WHERE speaker_enrollment_complete = TRUE AND is_active = TRUE;

-- ============================================================
-- 2. PERMISSIONS
-- ============================================================

-- 2.1 Home Assistant
CREATE TABLE IF NOT EXISTS alice.permissions_home_assistant (
    id                  SERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    domain              VARCHAR(50) NOT NULL,
    can_read            BOOLEAN DEFAULT FALSE,
    can_control         BOOLEAN DEFAULT FALSE,
    allowed_areas       JSONB DEFAULT NULL,
    allowed_entities    JSONB DEFAULT NULL,
    denied_entities     JSONB DEFAULT NULL,
    time_restrictions   JSONB DEFAULT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, domain)
);

CREATE INDEX IF NOT EXISTS idx_perm_ha_user   ON alice.permissions_home_assistant(user_id);
CREATE INDEX IF NOT EXISTS idx_perm_ha_domain ON alice.permissions_home_assistant(domain);

-- 2.2 System
CREATE TABLE IF NOT EXISTS alice.permissions_system (
    id                      SERIAL PRIMARY KEY,
    user_id                 UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    can_manage_users        BOOLEAN DEFAULT FALSE,
    can_manage_devices      BOOLEAN DEFAULT FALSE,
    can_view_logs           BOOLEAN DEFAULT FALSE,
    can_manage_workflows    BOOLEAN DEFAULT FALSE,
    can_access_api_docs     BOOLEAN DEFAULT FALSE,
    can_manage_memory       BOOLEAN DEFAULT FALSE,
    can_delete_memory       BOOLEAN DEFAULT FALSE,
    can_manage_dms_folders  BOOLEAN DEFAULT FALSE,
    can_view_chat_archive   BOOLEAN DEFAULT FALSE,
    can_manage_mailboxes    BOOLEAN DEFAULT FALSE,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);

-- 2.3 Assistant
CREATE TABLE IF NOT EXISTS alice.permissions_assistant (
    id                          SERIAL PRIMARY KEY,
    user_id                     UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    can_use_chat                BOOLEAN DEFAULT TRUE,
    can_use_voice               BOOLEAN DEFAULT TRUE,
    can_use_tools               BOOLEAN DEFAULT TRUE,
    tools_allowed               JSONB DEFAULT '["*"]',
    tools_denied                JSONB DEFAULT '[]',
    max_messages_per_day        INT DEFAULT NULL,
    max_tokens_per_message      INT DEFAULT NULL,
    can_access_shared_memory    BOOLEAN DEFAULT FALSE,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ DEFAULT NOW(),
    can_use_timers              BOOLEAN DEFAULT TRUE,
    can_use_calendar            BOOLEAN DEFAULT FALSE,
    can_use_lists               BOOLEAN DEFAULT FALSE,
    UNIQUE(user_id)
);

-- ============================================================
-- 3. ROLE TEMPLATES
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.role_templates (
    role                    VARCHAR(20) PRIMARY KEY,
    description             TEXT,
    ha_permissions          JSONB NOT NULL,
    system_permissions      JSONB NOT NULL,
    assistant_permissions   JSONB NOT NULL
);

INSERT INTO alice.role_templates
    (role, description, ha_permissions, system_permissions, assistant_permissions)
VALUES
(
    'admin',
    'Vollzugriff auf alle Funktionen',
    '[{"domain": "*", "can_read": true, "can_control": true}]',
    '{"can_manage_users": true, "can_manage_devices": true, "can_view_logs": true, "can_manage_workflows": true, "can_access_api_docs": true, "can_manage_memory": true, "can_delete_memory": true, "can_manage_dms_folders": true, "can_view_chat_archive": true, "can_manage_mailboxes": true}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["*"], "can_use_timers": true, "timer_max_active": 20, "timer_max_duration_seconds": 86400, "can_use_calendar": true, "can_use_lists": true}'
),
(
    'haushalt',
    'Haushaltsmitglied: alle Dokumente, Mails, Bilder; keine Verwaltung',
    '[
        {"domain": "light",               "can_read": true,  "can_control": true},
        {"domain": "switch",              "can_read": true,  "can_control": true},
        {"domain": "climate",             "can_read": true,  "can_control": true},
        {"domain": "sensor",              "can_read": true,  "can_control": false},
        {"domain": "media_player",        "can_read": true,  "can_control": true},
        {"domain": "cover",               "can_read": true,  "can_control": true},
        {"domain": "vacuum",              "can_read": true,  "can_control": true},
        {"domain": "alarm_control_panel", "can_read": true,  "can_control": false}
    ]',
    '{"can_manage_users": false, "can_manage_devices": false, "can_view_logs": false, "can_manage_workflows": false, "can_access_api_docs": false, "can_manage_memory": true, "can_delete_memory": false, "can_manage_dms_folders": false, "can_view_chat_archive": false, "can_manage_mailboxes": false}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant", "search_documents", "get_document_details", "search_images", "search_emails", "get_email_body", "remember", "recall"], "can_use_timers": true, "timer_max_active": 10, "timer_max_duration_seconds": 86400, "can_use_calendar": true, "can_use_lists": true}'
),
(
    'guest',
    'Eingeschränkter Gast-Zugang',
    '[
        {"domain": "light",        "can_read": true, "can_control": true,  "allowed_areas": ["wohnzimmer", "gaestezimmer", "flur"]},
        {"domain": "climate",      "can_read": true, "can_control": false},
        {"domain": "sensor",       "can_read": true, "can_control": false},
        {"domain": "media_player", "can_read": true, "can_control": true,  "allowed_areas": ["wohnzimmer"]}
    ]',
    '{"can_manage_users": false, "can_manage_devices": false, "can_view_logs": false, "can_manage_workflows": false, "can_access_api_docs": false, "can_manage_memory": false, "can_delete_memory": false, "can_manage_dms_folders": false, "can_view_chat_archive": false, "can_manage_mailboxes": false}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant"], "max_messages_per_day": 50, "can_use_timers": false, "timer_max_active": 0, "timer_max_duration_seconds": 0, "can_use_calendar": false, "can_use_lists": false}'
)
ON CONFLICT (role) DO NOTHING;

-- ============================================================
-- 4. PERMISSION HELPER FUNCTIONS
-- ============================================================

-- Initialize permissions for a new user from role template
CREATE OR REPLACE FUNCTION alice.init_user_permissions(
    p_user_id UUID,
    p_role    VARCHAR(20)
) RETURNS VOID AS $$
DECLARE
    v_template alice.role_templates%ROWTYPE;
    v_ha_perm  JSONB;
BEGIN
    SELECT * INTO v_template FROM alice.role_templates WHERE role = p_role;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Role template % not found', p_role;
    END IF;

    -- Home Assistant permissions
    FOR v_ha_perm IN SELECT * FROM jsonb_array_elements(v_template.ha_permissions)
    LOOP
        INSERT INTO alice.permissions_home_assistant (
            user_id, domain, can_read, can_control,
            allowed_areas, allowed_entities, denied_entities, time_restrictions
        ) VALUES (
            p_user_id,
            v_ha_perm->>'domain',
            COALESCE((v_ha_perm->>'can_read')::boolean,    false),
            COALESCE((v_ha_perm->>'can_control')::boolean, false),
            v_ha_perm->'allowed_areas',
            v_ha_perm->'allowed_entities',
            v_ha_perm->'denied_entities',
            v_ha_perm->'time_restrictions'
        )
        ON CONFLICT (user_id, domain) DO UPDATE SET
            can_read          = EXCLUDED.can_read,
            can_control       = EXCLUDED.can_control,
            allowed_areas     = EXCLUDED.allowed_areas,
            allowed_entities  = EXCLUDED.allowed_entities,
            denied_entities   = EXCLUDED.denied_entities,
            time_restrictions = EXCLUDED.time_restrictions,
            updated_at        = NOW();
    END LOOP;

    -- System permissions
    INSERT INTO alice.permissions_system (
        user_id,
        can_manage_users, can_manage_devices, can_view_logs,
        can_manage_workflows, can_access_api_docs, can_manage_memory, can_delete_memory,
        can_manage_dms_folders, can_view_chat_archive, can_manage_mailboxes
    ) VALUES (
        p_user_id,
        COALESCE((v_template.system_permissions->>'can_manage_users')::boolean,      false),
        COALESCE((v_template.system_permissions->>'can_manage_devices')::boolean,    false),
        COALESCE((v_template.system_permissions->>'can_view_logs')::boolean,         false),
        COALESCE((v_template.system_permissions->>'can_manage_workflows')::boolean,  false),
        COALESCE((v_template.system_permissions->>'can_access_api_docs')::boolean,   false),
        COALESCE((v_template.system_permissions->>'can_manage_memory')::boolean,     false),
        COALESCE((v_template.system_permissions->>'can_delete_memory')::boolean,     false),
        COALESCE((v_template.system_permissions->>'can_manage_dms_folders')::boolean, false),
        COALESCE((v_template.system_permissions->>'can_view_chat_archive')::boolean,  false),
        COALESCE((v_template.system_permissions->>'can_manage_mailboxes')::boolean,   false)
    )
    ON CONFLICT (user_id) DO UPDATE SET
        can_manage_users     = EXCLUDED.can_manage_users,
        can_manage_devices   = EXCLUDED.can_manage_devices,
        can_view_logs        = EXCLUDED.can_view_logs,
        can_manage_workflows = EXCLUDED.can_manage_workflows,
        can_access_api_docs  = EXCLUDED.can_access_api_docs,
        can_manage_memory    = EXCLUDED.can_manage_memory,
        can_delete_memory    = EXCLUDED.can_delete_memory,
        can_manage_dms_folders = EXCLUDED.can_manage_dms_folders,
        can_view_chat_archive  = EXCLUDED.can_view_chat_archive,
        can_manage_mailboxes   = EXCLUDED.can_manage_mailboxes,
        updated_at           = NOW();

    -- Assistant permissions
    INSERT INTO alice.permissions_assistant (
        user_id,
        can_use_chat, can_use_voice, can_use_tools,
        tools_allowed, tools_denied, max_messages_per_day, can_access_shared_memory,
        can_use_timers, can_use_calendar, can_use_lists
    ) VALUES (
        p_user_id,
        COALESCE((v_template.assistant_permissions->>'can_use_chat')::boolean,   true),
        COALESCE((v_template.assistant_permissions->>'can_use_voice')::boolean,  true),
        COALESCE((v_template.assistant_permissions->>'can_use_tools')::boolean,  true),
        COALESCE(v_template.assistant_permissions->'tools_allowed', '["*"]'::jsonb),
        COALESCE(v_template.assistant_permissions->'tools_denied',  '[]'::jsonb),
        (v_template.assistant_permissions->>'max_messages_per_day')::int,
        COALESCE((v_template.assistant_permissions->>'can_access_shared_memory')::boolean, false),
        COALESCE((v_template.assistant_permissions->>'can_use_timers')::boolean, true),
        COALESCE((v_template.assistant_permissions->>'can_use_calendar')::boolean, false),
        COALESCE((v_template.assistant_permissions->>'can_use_lists')::boolean, false)
    )
    ON CONFLICT (user_id) DO UPDATE SET
        can_use_chat             = EXCLUDED.can_use_chat,
        can_use_voice            = EXCLUDED.can_use_voice,
        can_use_tools            = EXCLUDED.can_use_tools,
        tools_allowed            = EXCLUDED.tools_allowed,
        tools_denied             = EXCLUDED.tools_denied,
        max_messages_per_day     = EXCLUDED.max_messages_per_day,
        can_access_shared_memory = EXCLUDED.can_access_shared_memory,
        can_use_timers           = EXCLUDED.can_use_timers,
        can_use_calendar         = EXCLUDED.can_use_calendar,
        can_use_lists            = EXCLUDED.can_use_lists,
        updated_at               = NOW();
END;
$$ LANGUAGE plpgsql;

-- Check whether a user may perform a HA action
CREATE OR REPLACE FUNCTION alice.check_ha_permission(
    p_user_id  UUID,
    p_domain   VARCHAR(50),
    p_entity_id VARCHAR(255),
    p_action   VARCHAR(20),   -- 'read' or 'control'
    p_area     VARCHAR(100) DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_perm          alice.permissions_home_assistant%ROWTYPE;
    v_wildcard_perm alice.permissions_home_assistant%ROWTYPE;
    v_has_permission BOOLEAN := FALSE;
BEGIN
    SELECT * INTO v_perm
    FROM alice.permissions_home_assistant
    WHERE user_id = p_user_id AND domain = p_domain;

    IF NOT FOUND THEN
        SELECT * INTO v_wildcard_perm
        FROM alice.permissions_home_assistant
        WHERE user_id = p_user_id AND domain = '*';
        IF NOT FOUND THEN RETURN FALSE; END IF;
        v_perm := v_wildcard_perm;
    END IF;

    IF p_action = 'read'    THEN v_has_permission := v_perm.can_read;
    ELSIF p_action = 'control' THEN v_has_permission := v_perm.can_control;
    END IF;

    IF NOT v_has_permission THEN RETURN FALSE; END IF;

    IF v_perm.denied_entities IS NOT NULL AND v_perm.denied_entities ? p_entity_id THEN
        RETURN FALSE;
    END IF;

    IF v_perm.allowed_entities IS NOT NULL AND NOT v_perm.allowed_entities ? p_entity_id THEN
        RETURN FALSE;
    END IF;

    IF v_perm.allowed_areas IS NOT NULL AND p_area IS NOT NULL THEN
        IF NOT v_perm.allowed_areas ? p_area THEN RETURN FALSE; END IF;
    END IF;

    IF v_perm.time_restrictions IS NOT NULL THEN
        DECLARE
            v_start TIME;
            v_end   TIME;
            v_now   TIME := LOCALTIME;
        BEGIN
            v_start := (v_perm.time_restrictions->'allowed_hours'->>'start')::TIME;
            v_end   := (v_perm.time_restrictions->'allowed_hours'->>'end')::TIME;
            IF v_now < v_start OR v_now > v_end THEN RETURN FALSE; END IF;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END IF;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 5. AUTH SESSIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.auth_sessions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    token_hash    VARCHAR(255) NOT NULL,
    device_info   JSONB,
    ip_address    INET,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    expires_at    TIMESTAMPTZ NOT NULL,
    last_activity TIMESTAMPTZ DEFAULT NOW(),
    is_valid      BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_token ON alice.auth_sessions(token_hash) WHERE is_valid = TRUE;
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user  ON alice.auth_sessions(user_id, expires_at);

-- WebAuthn Challenges (Phase 2)
CREATE TABLE IF NOT EXISTS alice.webauthn_challenges (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES alice.users(id) ON DELETE CASCADE,
    challenge  TEXT NOT NULL,
    type       VARCHAR(20) NOT NULL CHECK (type IN ('registration', 'authentication')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '5 minutes'),
    used       BOOLEAN DEFAULT FALSE
);

-- ============================================================
-- 6. CHAT MEMORY
-- ============================================================

-- Session metadata
CREATE TABLE IF NOT EXISTS alice.sessions (
    session_id    UUID PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    title         VARCHAR(255),
    started_at    TIMESTAMPTZ DEFAULT NOW(),
    last_activity TIMESTAMPTZ DEFAULT NOW(),
    message_count INT DEFAULT 0,
    summary       TEXT,
    key_topics    TEXT[],
    is_active     BOOLEAN DEFAULT TRUE,
    -- PROJ-51: chat storage classification & retention
    session_type  TEXT NOT NULL DEFAULT 'llm' CHECK (session_type IN ('llm', 'ha_only')),
    expires_at    TIMESTAMPTZ,
    source        TEXT CHECK (source IS NULL OR source IN ('webapp_cc', 'webapp_mic', 'esphome') OR source LIKE 'esphome:%')
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON alice.sessions(user_id, last_activity DESC);

-- PROJ-51: cleanup index for expired ha_only sessions
CREATE INDEX IF NOT EXISTS idx_sessions_cleanup
    ON alice.sessions(session_type, expires_at)
    WHERE session_type = 'ha_only' AND expires_at IS NOT NULL;

ALTER TABLE alice.sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sessions_allow_all ON alice.sessions;
CREATE POLICY sessions_allow_all ON alice.sessions
    FOR ALL USING (true) WITH CHECK (true);

-- Per-message storage (Tier 1 working memory)
-- user_id and session_id are UUID FKs
CREATE TABLE IF NOT EXISTS alice.messages (
    id                      SERIAL PRIMARY KEY,
    session_id              UUID NOT NULL REFERENCES alice.sessions(session_id) ON DELETE CASCADE,
    user_id                 UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    role                    VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content                 TEXT NOT NULL,
    tool_calls              JSONB,
    tool_results            JSONB,
    timestamp               TIMESTAMPTZ DEFAULT NOW(),
    token_count             INT,
    transferred_to_weaviate BOOLEAN DEFAULT FALSE,
    transferred_at          TIMESTAMPTZ,
    weaviate_id             UUID,
    -- PROJ-51: display-type for session restore
    msg_type                TEXT CHECK (msg_type IN ('user_text', 'user_stt', 'llm_thinking', 'llm_response', 'ha_result', 'tool_result'))
);

CREATE INDEX IF NOT EXISTS idx_messages_session         ON alice.messages(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_user_recent     ON alice.messages(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_messages_msg_type        ON alice.messages(session_id, msg_type);
CREATE INDEX IF NOT EXISTS idx_messages_not_transferred ON alice.messages(user_id)
    WHERE transferred_to_weaviate = FALSE;

ALTER TABLE alice.messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS messages_allow_all ON alice.messages;
CREATE POLICY messages_allow_all ON alice.messages
    FOR ALL USING (true) WITH CHECK (true);

-- User profiles (Tier 3: summarized permanent facts)
CREATE TABLE IF NOT EXISTS alice.user_profiles (
    user_id      VARCHAR(255) PRIMARY KEY,
    facts        JSONB DEFAULT '{}',
    preferences  JSONB DEFAULT '{}',
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 7. DMS INFRASTRUCTURE
-- ============================================================

-- NAS folders watched by the DMS scanner workflow
CREATE TABLE IF NOT EXISTS alice.dms_watched_folders (
    id             SERIAL PRIMARY KEY,
    path           TEXT NOT NULL UNIQUE CHECK (char_length(path) <= 500),
    suggested_type TEXT CHECK (suggested_type IN (
                       'Invoice', 'BankStatement', 'Document', 'Email',
                       'SecuritySettlement', 'Contract', 'Image'
                   )),
    description    TEXT,
    enabled        BOOLEAN NOT NULL DEFAULT true,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dms_watched_folders_enabled
    ON alice.dms_watched_folders(enabled);

CREATE INDEX IF NOT EXISTS idx_dms_watched_folders_sort_order
    ON alice.dms_watched_folders(sort_order ASC);

DROP TRIGGER IF EXISTS trg_dms_watched_folders_updated_at ON alice.dms_watched_folders;
CREATE TRIGGER trg_dms_watched_folders_updated_at
    BEFORE UPDATE ON alice.dms_watched_folders
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

ALTER TABLE alice.dms_watched_folders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS dms_watched_folders_allow_all ON alice.dms_watched_folders;
CREATE POLICY dms_watched_folders_allow_all ON alice.dms_watched_folders
    FOR ALL USING (true) WITH CHECK (true);

-- ============================================================
-- 8. HOME ASSISTANT SYNC
-- ============================================================

-- 8.1 Intent templates: vocabulary of HA commands
CREATE TABLE IF NOT EXISTS alice.ha_intent_templates (
    id                    SERIAL PRIMARY KEY,
    domain                VARCHAR(50)  NOT NULL,
    intent                VARCHAR(100) NOT NULL,
    service               VARCHAR(100) NOT NULL,
    patterns              JSONB        NOT NULL DEFAULT '[]',
    default_parameters    JSONB        NOT NULL DEFAULT '{}',
    requires_confirmation BOOLEAN      NOT NULL DEFAULT FALSE,
    language              VARCHAR(10)  NOT NULL DEFAULT 'de',
    priority              SMALLINT     NOT NULL DEFAULT 50,
    is_active             BOOLEAN      NOT NULL DEFAULT TRUE,
    source                VARCHAR(50)  NOT NULL DEFAULT 'seed',
    notes                 TEXT,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (domain, intent, language)
);

CREATE INDEX IF NOT EXISTS idx_ha_intent_templates_domain
    ON alice.ha_intent_templates(domain);

CREATE INDEX IF NOT EXISTS idx_ha_intent_templates_is_active
    ON alice.ha_intent_templates(is_active);

CREATE INDEX IF NOT EXISTS idx_ha_intent_templates_domain_active
    ON alice.ha_intent_templates(domain, is_active)
    WHERE is_active = TRUE;

DROP TRIGGER IF EXISTS trg_ha_intent_templates_updated_at ON alice.ha_intent_templates;
CREATE TRIGGER trg_ha_intent_templates_updated_at
    BEFORE UPDATE ON alice.ha_intent_templates
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

ALTER TABLE alice.ha_intent_templates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ha_intent_templates_select ON alice.ha_intent_templates;
CREATE POLICY ha_intent_templates_select ON alice.ha_intent_templates FOR SELECT USING (TRUE);

DROP POLICY IF EXISTS ha_intent_templates_insert ON alice.ha_intent_templates;
CREATE POLICY ha_intent_templates_insert ON alice.ha_intent_templates FOR INSERT WITH CHECK (TRUE);

DROP POLICY IF EXISTS ha_intent_templates_update ON alice.ha_intent_templates;
CREATE POLICY ha_intent_templates_update ON alice.ha_intent_templates FOR UPDATE USING (TRUE);

DROP POLICY IF EXISTS ha_intent_templates_delete ON alice.ha_intent_templates;
CREATE POLICY ha_intent_templates_delete ON alice.ha_intent_templates FOR DELETE USING (TRUE);

-- Seed: 19 German intent templates across 8 domains
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
-- cover
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
-- lock (requires confirmation)
('lock', 'lock', 'lock.lock',
 '["Schloss {name} sperren","{name} abschließen","Tür {name} sperren"]',
 '{}', TRUE, 'de', 70, 'seed'),
('lock', 'unlock', 'lock.unlock',
 '["Schloss {name} öffnen","{name} aufschließen","Tür {name} öffnen"]',
 '{}', TRUE, 'de', 70, 'seed'),
-- alarm_control_panel (requires confirmation)
('alarm_control_panel', 'alarm_arm_away', 'alarm_control_panel.alarm_arm_away',
 '["Alarm aktivieren","Alarmanlage scharf schalten","Haus sichern"]',
 '{}', TRUE, 'de', 80, 'seed'),
('alarm_control_panel', 'alarm_disarm', 'alarm_control_panel.alarm_disarm',
 '["Alarm deaktivieren","Alarmanlage deaktivieren","Alarm aus"]',
 '{}', TRUE, 'de', 80, 'seed')
ON CONFLICT (domain, intent, language) DO NOTHING;

-- Seed: variable cover position. {value} is expanded to percent anchors by
-- alice-ha-sync; the exact value is re-extracted in alice-chat-stream.
INSERT INTO alice.ha_intent_templates
    (domain, intent, service, patterns, default_parameters,
     requires_confirmation, language, priority, is_active, source, notes)
VALUES (
    'cover',
    'set_position',
    'cover.set_cover_position',
    '[
        "Rolladen in der {area} auf {value} Prozent",
        "Rolladen in der {area} auf {value} Prozent stellen",
        "Rolladen in der {area} auf {value} Prozent fahren",
        "Rolladen {name} auf {value} Prozent",
        "Rolladen {name} auf {value} Prozent stellen",
        "Jalousie {name} auf {value} Prozent",
        "{name} auf {value} Prozent stellen"
    ]'::jsonb,
    '{}'::jsonb,
    false,
    'de',
    55,
    true,
    'seed',
    'PROJ-83 — variable cover position. {value} expanded to percent anchors by alice-ha-sync; exact value re-extracted in alice-chat-stream.'
)
ON CONFLICT (domain, intent, language)
DO UPDATE SET
    service            = EXCLUDED.service,
    patterns           = EXCLUDED.patterns,
    default_parameters = EXCLUDED.default_parameters,
    priority           = EXCLUDED.priority,
    is_active          = TRUE,
    notes              = EXCLUDED.notes,
    updated_at         = NOW();

-- Seed: entity-less timer intents. alice-ha-sync skips them (no HA entity);
-- scripts/seed-timer-intents.sh writes the patterns verbatim into the Weaviate
-- HAIntent collection as the vectorised utterance. So the patterns MUST be
-- concrete natural sentences with NO {value}/{name} placeholders: the
-- duration / clock / name / delta is re-extracted from the live transcript in
-- app/timers.py after the semantic match.
INSERT INTO alice.ha_intent_templates
    (domain, intent, service, patterns, default_parameters,
     requires_confirmation, language, priority, is_active, source, notes)
VALUES
('timer', 'set',    'timer.set',
 '["Setze einen Timer auf 20 Minuten","Stelle einen Timer auf 15 Minuten","Timer auf 10 Minuten","Stell mir einen Timer auf eine Stunde","Setze einen Timer auf 1 Stunde 30 Minuten","Stelle einen Timer für die Kartoffeln auf 20 Minuten","Setze einen Timer für den Tee auf 5 Minuten","Stelle einen Timer auf 15 Uhr 40","Setze einen Timer auf 7 Uhr","Wecke mich in 25 Minuten","Erinnere mich in 10 Minuten","Neuer Timer 30 Minuten"]'::jsonb,
 '{}'::jsonb, false, 'de', 65, true, 'seed',
 'PROJ-85 — entity-less timer intent. Duration/time/name re-parsed in alice-chat-stream app/timers.py.'),
-- extend/shorten: deliberately NO example durations. nearText ranks a
-- literal number match so strongly that "Timer auf 2 Minuten" (set) matched
-- "Stell den Timer 2 Minuten früher" (shorten) at 0.97 — any digit shared
-- with a set/query utterance can hijack the ranking regardless of sentence
-- structure. The verb + "Timer" pattern alone carries the intent; the exact
-- delta is re-extracted from the live transcript in app/timers.py regardless
-- (PROJ-85 QA follow-up, live-verified 2026-09-16).
('timer', 'extend',  'timer.extend',
 '["Verlängere den Kartoffel Timer","Verlängere den Timer","Gib dem Timer noch etwas dazu","Stell den Timer später","Mach den Timer länger"]'::jsonb,
 '{}'::jsonb, false, 'de', 65, true, 'seed',
 'PROJ-85 — entity-less timer intent.'),
('timer', 'shorten', 'timer.shorten',
 '["Verkürze den Kartoffel Timer","Verkürze den Timer","Zieh dem Timer etwas ab","Stell den Timer früher","Mach den Timer kürzer"]'::jsonb,
 '{}'::jsonb, false, 'de', 65, true, 'seed',
 'PROJ-85 — entity-less timer intent.'),
('timer', 'query',   'timer.query',
 '["Wie lange läuft der Kartoffel Timer noch","Wie lange läuft der Timer noch","Wie viel Zeit ist noch auf dem Timer","Welche Timer laufen gerade","Welche Timer laufen","Zeig mir meine Timer","Was für Timer habe ich gerade","Läuft noch ein Timer"]'::jsonb,
 '{}'::jsonb, false, 'de', 65, true, 'seed',
 'PROJ-85 — entity-less timer intent.'),
('timer', 'pause',   'timer.pause',
 '["Pausiere den Kartoffel Timer","Pausiere den Timer","Halte den Timer an","Stoppe den Timer kurz","Unterbrich den Timer"]'::jsonb,
 '{}'::jsonb, false, 'de', 65, true, 'seed',
 'PROJ-85 — entity-less timer intent.'),
('timer', 'resume',  'timer.resume',
 '["Setze den Kartoffel Timer fort","Setze den Timer fort","Starte den Timer wieder","Lass den Timer weiterlaufen","Mach beim Timer weiter"]'::jsonb,
 '{}'::jsonb, false, 'de', 65, true, 'seed',
 'PROJ-85 — entity-less timer intent.'),
('timer', 'delete',  'timer.delete',
 '["Lösche den Kartoffel Timer","Lösche den Timer","Brich den Timer ab","Entferne den Timer","Stoppe den Timer ganz","Lösche alle Timer","Brich alle Timer ab"]'::jsonb,
 '{}'::jsonb, false, 'de', 65, true, 'seed',
 'PROJ-85 — entity-less timer intent.')
ON CONFLICT (domain, intent, language)
DO UPDATE SET
    service            = EXCLUDED.service,
    patterns           = EXCLUDED.patterns,
    priority           = EXCLUDED.priority,
    is_active          = TRUE,
    notes              = EXCLUDED.notes,
    updated_at         = NOW();

-- 8.2 HA entity registry mirror
CREATE TABLE IF NOT EXISTS alice.ha_entities (
    id                 SERIAL PRIMARY KEY,
    entity_id          VARCHAR(255) NOT NULL UNIQUE,
    domain             VARCHAR(50)  NOT NULL,
    friendly_name      VARCHAR(255),
    area_id            VARCHAR(100),
    area_name          VARCHAR(100),
    aliases            JSONB        NOT NULL DEFAULT '[]',
    device_class       VARCHAR(100),
    supported_features INTEGER,
    last_seen_at       TIMESTAMPTZ,
    is_active          BOOLEAN      NOT NULL DEFAULT TRUE,
    weaviate_synced    BOOLEAN      NOT NULL DEFAULT FALSE,
    intents_count      INT          NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ha_entities_domain
    ON alice.ha_entities(domain);

CREATE INDEX IF NOT EXISTS idx_ha_entities_is_active
    ON alice.ha_entities(is_active);

CREATE INDEX IF NOT EXISTS idx_ha_entities_sync_pending
    ON alice.ha_entities(is_active, weaviate_synced)
    WHERE is_active = TRUE AND weaviate_synced = FALSE;

DROP TRIGGER IF EXISTS trg_ha_entities_updated_at ON alice.ha_entities;
CREATE TRIGGER trg_ha_entities_updated_at
    BEFORE UPDATE ON alice.ha_entities
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

ALTER TABLE alice.ha_entities ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ha_entities_select ON alice.ha_entities;
CREATE POLICY ha_entities_select ON alice.ha_entities FOR SELECT USING (TRUE);

DROP POLICY IF EXISTS ha_entities_insert ON alice.ha_entities;
CREATE POLICY ha_entities_insert ON alice.ha_entities FOR INSERT WITH CHECK (TRUE);

DROP POLICY IF EXISTS ha_entities_update ON alice.ha_entities;
CREATE POLICY ha_entities_update ON alice.ha_entities FOR UPDATE USING (TRUE);

DROP POLICY IF EXISTS ha_entities_delete ON alice.ha_entities;
CREATE POLICY ha_entities_delete ON alice.ha_entities FOR DELETE USING (TRUE);

-- 8.3 HA sync audit log
CREATE TABLE IF NOT EXISTS alice.ha_sync_log (
    id                SERIAL PRIMARY KEY,
    sync_type         VARCHAR(50)  NOT NULL,
    trigger_source    VARCHAR(50)  NOT NULL,
    entities_found    INT          NOT NULL DEFAULT 0,
    entities_added    INT          NOT NULL DEFAULT 0,
    entities_removed  INT          NOT NULL DEFAULT 0,
    entities_updated  INT          NOT NULL DEFAULT 0,
    intents_generated INT          NOT NULL DEFAULT 0,
    intents_removed   INT          NOT NULL DEFAULT 0,
    duration_ms       INT,
    status            VARCHAR(20)  NOT NULL DEFAULT 'running'
                          CHECK (status IN ('running', 'success', 'partial', 'error')),
    error_message     TEXT,
    details           JSONB        NOT NULL DEFAULT '{}',
    started_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ha_sync_log_started_at
    ON alice.ha_sync_log(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ha_sync_log_sync_type
    ON alice.ha_sync_log(sync_type);

ALTER TABLE alice.ha_sync_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ha_sync_log_select ON alice.ha_sync_log;
CREATE POLICY ha_sync_log_select ON alice.ha_sync_log FOR SELECT USING (TRUE);

DROP POLICY IF EXISTS ha_sync_log_insert ON alice.ha_sync_log;
CREATE POLICY ha_sync_log_insert ON alice.ha_sync_log FOR INSERT WITH CHECK (TRUE);

DROP POLICY IF EXISTS ha_sync_log_update ON alice.ha_sync_log;
CREATE POLICY ha_sync_log_update ON alice.ha_sync_log FOR UPDATE USING (TRUE);

DROP POLICY IF EXISTS ha_sync_log_delete ON alice.ha_sync_log;
CREATE POLICY ha_sync_log_delete ON alice.ha_sync_log FOR DELETE USING (TRUE);

-- ============================================================
-- 9. VIEWS
-- ============================================================

CREATE OR REPLACE VIEW alice.v_user_permissions_summary AS
SELECT
    u.username,
    u.display_name,
    u.role,
    u.is_active,
    (SELECT COUNT(*) FROM alice.permissions_home_assistant WHERE user_id = u.id AND can_control = TRUE) AS ha_control_domains,
    ps.can_manage_users,
    pa.max_messages_per_day
FROM alice.users u
LEFT JOIN alice.permissions_system    ps ON u.id = ps.user_id
LEFT JOIN alice.permissions_assistant pa ON u.id = pa.user_id;

CREATE OR REPLACE VIEW alice.v_ha_permissions AS
SELECT
    u.username,
    pha.domain,
    pha.can_read,
    pha.can_control,
    pha.allowed_areas,
    pha.allowed_entities,
    pha.time_restrictions
FROM alice.permissions_home_assistant pha
JOIN alice.users u ON pha.user_id = u.id
ORDER BY u.username, pha.domain;

-- ============================================================
-- 10. SYSTEM SETTINGS
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.system_settings (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    description TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_system_settings_updated_at ON alice.system_settings;
CREATE TRIGGER trg_system_settings_updated_at
    BEFORE UPDATE ON alice.system_settings
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

ALTER TABLE alice.system_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS system_settings_allow_all ON alice.system_settings;
CREATE POLICY system_settings_allow_all ON alice.system_settings
    FOR ALL USING (TRUE) WITH CHECK (TRUE);

-- Default role for a voice-set timer when the speaker was not recognised.
-- Shipping value 'haushalt'; an admin can change it in Settings.
INSERT INTO alice.system_settings (key, value, description)
VALUES (
    'timer_default_role',
    '"haushalt"'::jsonb,
    'Owner role assigned to a Voice-PE timer when the speaker was not identified.'
)
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- 11. TIMERS
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.timers (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Who set it. NULL when a Voice PE could not identify the speaker.
    owner_user_id            UUID REFERENCES alice.users(id) ON DELETE SET NULL,
    -- The ordering key for visibility, limits and "delete all timers".
    owner_role               VARCHAR(20) NOT NULL
                                 CHECK (owner_role IN ('admin', 'haushalt', 'guest')),
    -- Spoken / displayed name ("Kartoffel Timer", "20 Minuten Timer").
    name                     TEXT NOT NULL,
    -- Absolute moment the timer fires. Kept current while running; frozen
    -- semantics for paused timers live in paused_remaining_seconds.
    expires_at               TIMESTAMPTZ NOT NULL,
    status                   VARCHAR(16) NOT NULL DEFAULT 'running'
                                 CHECK (status IN ('running', 'paused', 'expired', 'acknowledged')),
    -- Seconds left at the moment of pause; NULL unless status = 'paused'.
    paused_remaining_seconds INT,
    -- Origin channel: the Voice-PE device key (device-mapping.yaml) for the
    -- melody delivery, or 'webapp' for a browser-set timer.
    origin_channel           TEXT NOT NULL,
    -- Set true once the expiry has been announced / delivered, so the
    -- restart reconcile and the scheduler never fire the same timer twice.
    fired_at                 TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Who ended the alarm. The WebApp catch-up message is only shown for timers
    -- nobody actively acknowledged (still 'expired', or 'timeout').
    acknowledged_by          VARCHAR(16)
                                 CHECK (acknowledged_by IN ('voice', 'webapp', 'timeout'))
);

COMMENT ON COLUMN alice.timers.acknowledged_by IS
    'Who ended the expiry alarm: voice | webapp | timeout. NULL while not acknowledged.';

DROP TRIGGER IF EXISTS trg_timers_updated_at ON alice.timers;
CREATE TRIGGER trg_timers_updated_at
    BEFORE UPDATE ON alice.timers
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

-- Scheduler wakes on the next running expiry; handler lists per role.
CREATE INDEX IF NOT EXISTS idx_timers_owner_role ON alice.timers(owner_role);
CREATE INDEX IF NOT EXISTS idx_timers_status     ON alice.timers(status);
CREATE INDEX IF NOT EXISTS idx_timers_due
    ON alice.timers(expires_at)
    WHERE status = 'running';
-- The announcement claim and the WebApp catch-up list filter expired /
-- recently acknowledged rows by fired_at.
CREATE INDEX IF NOT EXISTS idx_timers_fired_at
    ON alice.timers (fired_at)
    WHERE status IN ('expired', 'acknowledged');

ALTER TABLE alice.timers ENABLE ROW LEVEL SECURITY;
-- The chat-stream service connects as the schema owner and scopes every
-- query by owner_role itself (same pattern as alice.ha_entities). A single
-- permissive policy keeps RLS enabled without a second enforcement layer.
DROP POLICY IF EXISTS timers_allow_all ON alice.timers;
CREATE POLICY timers_allow_all ON alice.timers
    FOR ALL USING (TRUE) WITH CHECK (TRUE);

-- ============================================================
-- 12. IMAP MAILBOXES
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

DROP POLICY IF EXISTS imap_mailboxes_select ON alice.imap_mailboxes;
CREATE POLICY imap_mailboxes_select ON alice.imap_mailboxes FOR SELECT USING (TRUE);
DROP POLICY IF EXISTS imap_mailboxes_insert ON alice.imap_mailboxes;
CREATE POLICY imap_mailboxes_insert ON alice.imap_mailboxes FOR INSERT WITH CHECK (TRUE);
DROP POLICY IF EXISTS imap_mailboxes_update ON alice.imap_mailboxes;
CREATE POLICY imap_mailboxes_update ON alice.imap_mailboxes FOR UPDATE USING (TRUE);
DROP POLICY IF EXISTS imap_mailboxes_delete ON alice.imap_mailboxes;
CREATE POLICY imap_mailboxes_delete ON alice.imap_mailboxes FOR DELETE USING (TRUE);

CREATE INDEX IF NOT EXISTS idx_imap_mailboxes_owner     ON alice.imap_mailboxes(owner_id);
CREATE INDEX IF NOT EXISTS idx_imap_mailboxes_next_sync ON alice.imap_mailboxes(next_sync_at);
CREATE INDEX IF NOT EXISTS idx_imap_mailboxes_status    ON alice.imap_mailboxes(status);

CREATE OR REPLACE TRIGGER set_updated_at_imap_mailboxes
    BEFORE UPDATE ON alice.imap_mailboxes
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

-- Mailboxes are visible to every 'admin' and 'haushalt' user (PROJ-121);
-- there is no per-user mailbox access table.

-- ============================================================
-- 13. GOOGLE CONNECTIONS & CALENDAR SELECTION
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.google_connections (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                  UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    google_account           VARCHAR(255) NOT NULL,   -- Google account email address
    scopes                   TEXT[] NOT NULL DEFAULT '{}',  -- granted OAuth scopes, free list
    access_token_enc         TEXT NOT NULL,           -- AES-256-CBC encrypted
    access_token_expires_at  TIMESTAMPTZ NOT NULL,
    refresh_token_enc        TEXT NOT NULL,           -- AES-256-CBC encrypted
    status                   VARCHAR(20) NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active', 'error')),
    last_error               TEXT,
    created_at               TIMESTAMPTZ DEFAULT NOW(),
    updated_at               TIMESTAMPTZ DEFAULT NOW(),
    -- Scope extensions update the existing row instead of creating a duplicate.
    CONSTRAINT google_connections_user_account_uniq UNIQUE (user_id, google_account),
    -- Composite key target so a selection row can reference (connection, owner):
    -- the selection's user_id is then guaranteed to be the connection's owner.
    CONSTRAINT google_connections_id_user_uniq UNIQUE (id, user_id)
);

ALTER TABLE alice.google_connections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS google_connections_select ON alice.google_connections;
CREATE POLICY google_connections_select ON alice.google_connections FOR SELECT USING (TRUE);
DROP POLICY IF EXISTS google_connections_insert ON alice.google_connections;
CREATE POLICY google_connections_insert ON alice.google_connections FOR INSERT WITH CHECK (TRUE);
DROP POLICY IF EXISTS google_connections_update ON alice.google_connections;
CREATE POLICY google_connections_update ON alice.google_connections FOR UPDATE USING (TRUE);
DROP POLICY IF EXISTS google_connections_delete ON alice.google_connections;
CREATE POLICY google_connections_delete ON alice.google_connections FOR DELETE USING (TRUE);

CREATE INDEX IF NOT EXISTS idx_google_connections_user ON alice.google_connections(user_id);

CREATE OR REPLACE TRIGGER set_updated_at_google_connections
    BEFORE UPDATE ON alice.google_connections
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();
-- Which Google calendars of a connection the user enabled for Alice, plus the
-- single default calendar per user. Only selection metadata: no event data.
CREATE TABLE IF NOT EXISTS alice.calendar_selections (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL,
    -- Denormalised owner so "one default calendar per user" is a DB constraint.
    user_id       UUID NOT NULL,
    calendar_id   TEXT NOT NULL,             -- Google calendar id
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    is_default    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Disconnecting the Google account deletes its selection (spec).
    CONSTRAINT calendar_selections_connection_fk
        FOREIGN KEY (connection_id, user_id)
        REFERENCES alice.google_connections (id, user_id) ON DELETE CASCADE,
    CONSTRAINT calendar_selections_conn_cal_uniq UNIQUE (connection_id, calendar_id),
    -- A default calendar must be active.
    CONSTRAINT calendar_selections_default_active CHECK (NOT is_default OR is_active)
);

-- At most one default calendar per user, across all connections.
CREATE UNIQUE INDEX IF NOT EXISTS idx_calendar_selections_one_default
    ON alice.calendar_selections(user_id) WHERE is_default;
CREATE INDEX IF NOT EXISTS idx_calendar_selections_user
    ON alice.calendar_selections(user_id);
CREATE INDEX IF NOT EXISTS idx_calendar_selections_connection
    ON alice.calendar_selections(connection_id);

DROP TRIGGER IF EXISTS trg_calendar_selections_updated_at ON alice.calendar_selections;
CREATE TRIGGER trg_calendar_selections_updated_at
    BEFORE UPDATE ON alice.calendar_selections
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

ALTER TABLE alice.calendar_selections ENABLE ROW LEVEL SECURITY;
-- alice-calendar connects as the schema owner and scopes every query by the
-- JWT's user_id itself (same pattern as alice.google_connections).
DROP POLICY IF EXISTS calendar_selections_select ON alice.calendar_selections;
DROP POLICY IF EXISTS calendar_selections_insert ON alice.calendar_selections;
DROP POLICY IF EXISTS calendar_selections_update ON alice.calendar_selections;
DROP POLICY IF EXISTS calendar_selections_delete ON alice.calendar_selections;
CREATE POLICY calendar_selections_select ON alice.calendar_selections FOR SELECT USING (TRUE);
CREATE POLICY calendar_selections_insert ON alice.calendar_selections FOR INSERT WITH CHECK (TRUE);
CREATE POLICY calendar_selections_update ON alice.calendar_selections FOR UPDATE USING (TRUE);
CREATE POLICY calendar_selections_delete ON alice.calendar_selections FOR DELETE USING (TRUE);

-- ============================================================
-- 14. LISTS
-- ============================================================

CREATE TABLE IF NOT EXISTS alice.lists (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 100),
    is_shared   BOOLEAN NOT NULL DEFAULT FALSE,
    -- Private lists only: the single user who may see / change them. Deleting
    -- the user deletes their private lists.
    owner_id    UUID REFERENCES alice.users(id) ON DELETE CASCADE,
    -- Creator (shared lists: may rename / delete besides admin). Deleting the
    -- user keeps their shared lists; afterwards only admin is responsible.
    created_by  UUID REFERENCES alice.users(id) ON DELETE SET NULL,
    is_shopping BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT lists_owner_matches_kind CHECK (
        (is_shared AND owner_id IS NULL) OR (NOT is_shared AND owner_id IS NOT NULL)
    ),
    CONSTRAINT lists_shopping_is_shared CHECK (NOT is_shopping OR is_shared)
);

-- Names are unique per visibility scope, case-insensitive: shared lists across
-- the household, private lists per owner. Another user's invisible private
-- list does not block a shared name (spec).
CREATE UNIQUE INDEX IF NOT EXISTS idx_lists_shared_name
    ON alice.lists (lower(btrim(name))) WHERE is_shared;
CREATE UNIQUE INDEX IF NOT EXISTS idx_lists_private_name
    ON alice.lists (owner_id, lower(btrim(name))) WHERE NOT is_shared;
-- At most one shopping list in the household.
CREATE UNIQUE INDEX IF NOT EXISTS idx_lists_one_shopping
    ON alice.lists ((TRUE)) WHERE is_shopping;
CREATE INDEX IF NOT EXISTS idx_lists_owner ON alice.lists (owner_id);
CREATE INDEX IF NOT EXISTS idx_lists_created_by ON alice.lists (created_by);

DROP TRIGGER IF EXISTS trg_lists_updated_at ON alice.lists;
CREATE TRIGGER trg_lists_updated_at
    BEFORE UPDATE ON alice.lists
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

-- ------------------------------------------------------------
-- List items
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alice.list_items (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    list_id           UUID NOT NULL REFERENCES alice.lists(id) ON DELETE CASCADE,
    title             TEXT NOT NULL CHECK (length(btrim(title)) >= 1),
    note              TEXT,
    -- Due = when to tackle it; deadline = by when it must be done. Date-only
    -- values are stored as local midnight with *_has_time = FALSE.
    due_at            TIMESTAMPTZ,
    due_has_time      BOOLEAN NOT NULL DEFAULT FALSE,
    deadline_at       TIMESTAMPTZ,
    deadline_has_time BOOLEAN NOT NULL DEFAULT FALSE,
    priority          TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('high', 'normal', 'low')),
    is_done           BOOLEAN NOT NULL DEFAULT FALSE,
    done_at           TIMESTAMPTZ,
    done_by           UUID REFERENCES alice.users(id) ON DELETE SET NULL,
    created_by        UUID REFERENCES alice.users(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT list_items_done_has_time CHECK (NOT is_done OR done_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_list_items_list_open ON alice.list_items (list_id, is_done);
CREATE INDEX IF NOT EXISTS idx_list_items_due ON alice.list_items (due_at) WHERE NOT is_done;
CREATE INDEX IF NOT EXISTS idx_list_items_deadline ON alice.list_items (deadline_at) WHERE NOT is_done;
-- Daily purge of items done more than 30 days ago.
CREATE INDEX IF NOT EXISTS idx_list_items_done_at ON alice.list_items (done_at) WHERE is_done;
CREATE INDEX IF NOT EXISTS idx_list_items_done_by ON alice.list_items (done_by);

DROP TRIGGER IF EXISTS trg_list_items_updated_at ON alice.list_items;
CREATE TRIGGER trg_list_items_updated_at
    BEFORE UPDATE ON alice.list_items
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

-- ------------------------------------------------------------
-- Default list per user
-- ------------------------------------------------------------
-- Kept beside alice.users instead of a column on it: no change to the auth
-- table. A deleted default list falls back to "Meine Aufgaben" (service).
CREATE TABLE IF NOT EXISTS alice.list_preferences (
    user_id         UUID PRIMARY KEY REFERENCES alice.users(id) ON DELETE CASCADE,
    default_list_id UUID REFERENCES alice.lists(id) ON DELETE SET NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_list_preferences_default ON alice.list_preferences (default_list_id);

-- ------------------------------------------------------------
-- RLS — alice-lists connects as the schema owner and scopes every query by
-- the JWT's user_id itself (same pattern as alice.calendar_selections);
-- private lists are filtered by owner_id in every query.
-- ------------------------------------------------------------
ALTER TABLE alice.lists ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.list_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.list_preferences ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['lists', 'list_items', 'list_preferences'] LOOP
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

-- Seed: the shared shopping list
INSERT INTO alice.lists (name, is_shared, is_shopping)
SELECT 'Einkaufsliste', TRUE, TRUE
WHERE NOT EXISTS (SELECT 1 FROM alice.lists WHERE is_shopping)
  AND NOT EXISTS (SELECT 1 FROM alice.lists WHERE is_shared AND lower(btrim(name)) = 'einkaufsliste');

-- ============================================================
-- 15. SERVICE USERS
-- ============================================================

-- wyoming_transport._token_for() mints a service JWT with
-- user_id = '00000000-0000-0000-0000-000000000000' for unidentified speakers.
-- alice-chat-stream's ensure_session() inserts into alice.sessions which has a
-- FK on alice.users(id) — without this row the insert fails with a FK violation
-- and alice-chat-stream returns 503 for every Wyoming voice turn.
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

-- ============================================================
-- 16. SOURCE OF TRUTH REGISTRY (PROJ-115)
-- ============================================================
-- Register of all sources (unique content = hash) of the source-of-truth repo,
-- their locations, mail parents and the processing state per pipeline stage.
-- Written only by alice-source-registry; no end-user access.

-- 16.1 Pipeline stages: extensible list, a new stage is a new row
CREATE TABLE IF NOT EXISTS alice.pipeline_stages (
    name                      VARCHAR(40) PRIMARY KEY CHECK (name ~ '^[a-z][a-z0-9_]{0,39}$'),
    position                  INTEGER     NOT NULL DEFAULT 100,
    skip_kinds                TEXT[]      NOT NULL DEFAULT '{}',
    resets_on_content_change  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO alice.pipeline_stages (name, position, skip_kinds, resets_on_content_change) VALUES
    ('detect',    10, '{}',              FALSE),
    ('extract',   20, '{audio,video}',   FALSE),
    ('classify',  30, '{audio,video}',   FALSE),
    ('database',  40, '{audio,video}',   TRUE),
    ('rag',       50, '{audio,video}',   TRUE),
    ('wiki',      60, '{audio,video}',   TRUE),
    ('thumbnail', 70, '{audio,video}',   FALSE)
ON CONFLICT (name) DO NOTHING;

-- PROJ-118: a stage can also go back to pending when certain frontmatter fields or the
-- content part (`content`) change, by another stage or by hand. classify: content and type.
ALTER TABLE alice.pipeline_stages ADD COLUMN IF NOT EXISTS resets_on_fields TEXT[] NOT NULL DEFAULT '{}';
UPDATE alice.pipeline_stages SET resets_on_fields = '{content,type}'
 WHERE name = 'classify' AND resets_on_fields = '{}';

-- 16.2 Sources: one row per unique content
CREATE TABLE IF NOT EXISTS alice.sources (
    id          VARCHAR(12)  PRIMARY KEY CHECK (id ~ '^[a-z0-9]{12}$'),
    kind        VARCHAR(10)  NOT NULL CHECK (kind IN ('document', 'image', 'email', 'audio', 'video')),
    hash        VARCHAR(128) NOT NULL,
    size        BIGINT,
    modified    TIMESTAMPTZ,
    captured    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    title       TEXT         NOT NULL,
    path        TEXT         NOT NULL,           -- markdown path relative to the repo root
    blob        VARCHAR(64),                     -- git blob id of the content last written/accepted by the pipeline
    repo_error  TEXT,                            -- set while the markdown is locked (invalid hand edit)
    repo_error_at TIMESTAMPTZ,
    deleted     BOOLEAN      NOT NULL DEFAULT FALSE,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_hash ON alice.sources(hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_path ON alice.sources(path);
CREATE INDEX IF NOT EXISTS idx_sources_repo_error ON alice.sources(id) WHERE repo_error IS NOT NULL;

DROP TRIGGER IF EXISTS trg_sources_updated_at ON alice.sources;
CREATE TRIGGER trg_sources_updated_at
    BEFORE UPDATE ON alice.sources
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

-- 16.3 Locations: NAS path or mailbox + message id
CREATE TABLE IF NOT EXISTS alice.source_locations (
    id          BIGSERIAL    PRIMARY KEY,
    source_id   VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    path        TEXT,
    mailbox     TEXT,
    message_id  TEXT,
    present     BOOLEAN      NOT NULL DEFAULT TRUE,
    first_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    gone_at     TIMESTAMPTZ,
    CHECK ((path IS NOT NULL AND mailbox IS NULL AND message_id IS NULL)
        OR (path IS NULL AND mailbox IS NOT NULL AND message_id IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_source_locations_key
    ON alice.source_locations(source_id, COALESCE(path, ''), COALESCE(mailbox, ''), COALESCE(message_id, ''));
CREATE INDEX IF NOT EXISTS idx_source_locations_path ON alice.source_locations(path) WHERE path IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_locations_mail ON alice.source_locations(mailbox, message_id) WHERE mailbox IS NOT NULL;

-- 16.4 Parents: attachment -> mail
CREATE TABLE IF NOT EXISTS alice.source_parents (
    source_id   VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    parent_id   VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, parent_id),
    CHECK (source_id <> parent_id)
);

CREATE INDEX IF NOT EXISTS idx_source_parents_parent ON alice.source_parents(parent_id);

-- 16.5 Stage state per source
CREATE TABLE IF NOT EXISTS alice.source_stages (
    source_id       VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    stage           VARCHAR(40)  NOT NULL REFERENCES alice.pipeline_stages(name) ON DELETE CASCADE,
    state           VARCHAR(20)  NOT NULL DEFAULT 'pending'
                    CHECK (state IN ('pending', 'running', 'done', 'failed', 'failed_permanent', 'skipped')),
    attempts        INTEGER      NOT NULL DEFAULT 0,
    last_error      TEXT,
    last_attempt_at TIMESTAMPTZ,
    next_retry_at   TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    claim_token     UUID,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_source_stages_due
    ON alice.source_stages(stage, state, next_retry_at) WHERE state IN ('pending', 'failed');
CREATE INDEX IF NOT EXISTS idx_source_stages_running
    ON alice.source_stages(started_at) WHERE state = 'running';

DROP TRIGGER IF EXISTS trg_source_stages_updated_at ON alice.source_stages;
CREATE TRIGGER trg_source_stages_updated_at
    BEFORE UPDATE ON alice.source_stages
    FOR EACH ROW EXECUTE FUNCTION alice.set_updated_at();

-- 16.6 Events per source (hand corrections, restores, locks) for later views (PROJ-122)
CREATE TABLE IF NOT EXISTS alice.source_events (
    id          BIGSERIAL    PRIMARY KEY,
    source_id   VARCHAR(12)  REFERENCES alice.sources(id) ON DELETE CASCADE,
    level       VARCHAR(10)  NOT NULL DEFAULT 'info' CHECK (level IN ('info', 'warning', 'error')),
    event       VARCHAR(40)  NOT NULL,
    message     TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_events_source ON alice.source_events(source_id, created_at DESC);

-- 16.7 RLS: only the service database user writes these tables
ALTER TABLE alice.pipeline_stages ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.source_locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.source_parents ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.source_stages ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.source_events ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['pipeline_stages', 'sources', 'source_locations', 'source_parents',
                             'source_stages', 'source_events'] LOOP
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

-- ============================================================
-- 17. FILE DETECTION (PROJ-116)
-- ============================================================
-- Working state of alice-file-detection. The source register (section 16) stays
-- the truth about sources and locations; these tables only mirror what the
-- detection service has seen on the NAS. Written only by alice-file-detection.

-- 17.1 Known files: one row per registered NAS path
CREATE TABLE IF NOT EXISTS alice.detect_files (
    path        TEXT         PRIMARY KEY,
    source_id   VARCHAR(12)  NOT NULL REFERENCES alice.sources(id) ON DELETE CASCADE,
    folder      TEXT         NOT NULL,           -- watched folder (path) the file belongs to
    size        BIGINT       NOT NULL,
    mtime_ns    BIGINT       NOT NULL,
    first_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detect_files_folder ON alice.detect_files(folder);
CREATE INDEX IF NOT EXISTS idx_detect_files_source ON alice.detect_files(source_id);

-- 17.2 Directory state for the day scan (only equality of mtime counts)
CREATE TABLE IF NOT EXISTS alice.detect_dirs (
    path        TEXT         PRIMARY KEY,
    folder      TEXT         NOT NULL,
    parent      TEXT,
    mtime_ns    BIGINT       NOT NULL,
    confirmed   BOOLEAN      NOT NULL DEFAULT FALSE,  -- same mtime seen by two scans
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detect_dirs_folder ON alice.detect_dirs(folder);
CREATE INDEX IF NOT EXISTS idx_detect_dirs_parent ON alice.detect_dirs(parent);

-- 17.3 New files waiting for stability (same size + mtime in two scans)
CREATE TABLE IF NOT EXISTS alice.detect_pending (
    path        TEXT         PRIMARY KEY,
    folder      TEXT         NOT NULL,
    size        BIGINT       NOT NULL,
    mtime_ns    BIGINT       NOT NULL,
    first_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detect_pending_folder ON alice.detect_pending(folder);

-- 17.4 Detection problems (unreadable files), retried by every scan
CREATE TABLE IF NOT EXISTS alice.detect_problems (
    path        TEXT         PRIMARY KEY,
    folder      TEXT         NOT NULL,
    cause       TEXT         NOT NULL,
    first_seen  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detect_problems_last_seen ON alice.detect_problems(last_seen DESC);

-- 17.5 Runs (day scan / nightly run) incl. the nightly summary (PROJ-122)
CREATE TABLE IF NOT EXISTS alice.detect_runs (
    id          BIGSERIAL    PRIMARY KEY,
    kind        VARCHAR(10)  NOT NULL CHECK (kind IN ('day', 'night')),
    trigger     VARCHAR(10)  NOT NULL DEFAULT 'schedule' CHECK (trigger IN ('schedule', 'manual', 'catchup')),
    state       VARCHAR(10)  NOT NULL DEFAULT 'running'
                CHECK (state IN ('running', 'done', 'paused', 'aborted', 'failed')),
    started_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    error       TEXT,
    summary     JSONB
);

CREATE INDEX IF NOT EXISTS idx_detect_runs_kind_started ON alice.detect_runs(kind, started_at DESC);

-- 17.6 RLS: only the service database user writes these tables
ALTER TABLE alice.detect_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.detect_dirs ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.detect_pending ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.detect_problems ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.detect_runs ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['detect_files', 'detect_dirs', 'detect_pending', 'detect_problems', 'detect_runs'] LOOP
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

-- ============================================================
-- 18. STRUCTURED DOCUMENT DATA (PROJ-119)
-- ============================================================
-- Derived from the frontmatter of classified source markdowns (kind `document`)
-- by alice-document-database (stage `database`). Rebuildable at any time from the
-- source of truth; never edited directly. One row per document, one detail row per
-- type, bookings and invoice line items as rows of their own. Amounts and
-- quantities as exact NUMERIC, dates as DATE, NULL stays NULL.

-- 18.1 Stage `database` also runs again when the locations change and when a
-- source is deleted or comes back (removes / re-enters its rows).
UPDATE alice.pipeline_stages SET resets_on_fields = '{locations,deleted}'
 WHERE name = 'database' AND resets_on_fields = '{}';

-- 18.2 One row per document (all types)
CREATE TABLE IF NOT EXISTS alice.doc_documents (
    id                          VARCHAR(12)  PRIMARY KEY,          -- source id (register)
    type                        VARCHAR(20)  NOT NULL
                                CHECK (type IN ('Invoice', 'BankStatement', 'SecuritySettlement', 'Contract', 'Document')),
    title                       TEXT,
    summary                     TEXT,
    tags                        TEXT[],
    document_date               DATE,
    sender                      TEXT,
    recipient                   TEXT,
    language                    TEXT,
    classification_confidence   NUMERIC,
    classification_uncertain    BOOLEAN,
    summary_language_uncertain  BOOLEAN,
    modified                    TIMESTAMPTZ,
    captured                    TIMESTAMPTZ,
    markdown_path               TEXT         NOT NULL,             -- path of the source markdown in the repo
    locations                   JSONB        NOT NULL DEFAULT '[]', -- locations of the originals as in the frontmatter
    synced_at                   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_documents_type ON alice.doc_documents(type);
CREATE INDEX IF NOT EXISTS idx_doc_documents_date ON alice.doc_documents(document_date);
CREATE INDEX IF NOT EXISTS idx_doc_documents_sender ON alice.doc_documents(sender);
CREATE INDEX IF NOT EXISTS idx_doc_documents_tags ON alice.doc_documents USING GIN (tags);

-- 18.3 Detail rows per type
CREATE TABLE IF NOT EXISTS alice.doc_invoices (
    document_id     VARCHAR(12) PRIMARY KEY REFERENCES alice.doc_documents(id) ON DELETE CASCADE,
    invoice_number  TEXT,
    invoice_date    DATE,
    due_date        DATE,
    amount_gross    NUMERIC,
    amount_net      NUMERIC,
    vat_rate        NUMERIC,
    currency        TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_invoices_date ON alice.doc_invoices(invoice_date);

CREATE TABLE IF NOT EXISTS alice.doc_invoice_line_items (
    document_id  VARCHAR(12) NOT NULL REFERENCES alice.doc_invoices(document_id) ON DELETE CASCADE,
    position     INTEGER     NOT NULL CHECK (position >= 1),
    description  TEXT,
    quantity     NUMERIC,
    amount       NUMERIC,
    PRIMARY KEY (document_id, position)
);

CREATE TABLE IF NOT EXISTS alice.doc_bank_statements (
    document_id         VARCHAR(12) PRIMARY KEY REFERENCES alice.doc_documents(id) ON DELETE CASCADE,
    bank_name           TEXT,
    account_holder      TEXT,
    iban                TEXT,
    period_from         DATE,
    period_to           DATE,
    opening_balance     NUMERIC,
    closing_balance     NUMERIC,
    currency            TEXT,
    balance_mismatch    BOOLEAN,
    balance_difference  NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_doc_bank_statements_iban ON alice.doc_bank_statements(iban);
CREATE INDEX IF NOT EXISTS idx_doc_bank_statements_period ON alice.doc_bank_statements(period_from, period_to);

-- Bookings; duplicate_of points to the booking that counts as the original when the same
-- booking (date, amount, purpose) is in an earlier captured statement of the same IBAN.
CREATE TABLE IF NOT EXISTS alice.doc_bank_transactions (
    id            BIGSERIAL   PRIMARY KEY,
    document_id   VARCHAR(12) NOT NULL REFERENCES alice.doc_bank_statements(document_id) ON DELETE CASCADE,
    position      INTEGER     NOT NULL CHECK (position >= 1),
    booking_date  DATE,
    value_date    DATE,
    counterparty  TEXT,
    purpose       TEXT,
    amount        NUMERIC,
    currency      TEXT,
    duplicate_of  BIGINT      REFERENCES alice.doc_bank_transactions(id) ON DELETE SET NULL,
    UNIQUE (document_id, position)
);

CREATE INDEX IF NOT EXISTS idx_doc_bank_transactions_booking ON alice.doc_bank_transactions(booking_date, amount);
CREATE INDEX IF NOT EXISTS idx_doc_bank_transactions_duplicate ON alice.doc_bank_transactions(duplicate_of)
    WHERE duplicate_of IS NOT NULL;

CREATE TABLE IF NOT EXISTS alice.doc_security_settlements (
    document_id        VARCHAR(12) PRIMARY KEY REFERENCES alice.doc_documents(id) ON DELETE CASCADE,
    bank               TEXT,
    depot_number       TEXT,
    transaction_date   DATE,
    security_name      TEXT,
    isin               TEXT,
    transaction_type   TEXT,
    quantity           NUMERIC,
    price              NUMERIC,
    settlement_amount  NUMERIC,
    currency           TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_security_settlements_isin ON alice.doc_security_settlements(isin);
CREATE INDEX IF NOT EXISTS idx_doc_security_settlements_date ON alice.doc_security_settlements(transaction_date);

CREATE TABLE IF NOT EXISTS alice.doc_contracts (
    document_id       VARCHAR(12) PRIMARY KEY REFERENCES alice.doc_documents(id) ON DELETE CASCADE,
    contract_type     TEXT,
    contract_partner  TEXT,
    sign_date         DATE,
    start_date        DATE,
    end_date          DATE,
    notice_period     TEXT,
    monthly_cost      NUMERIC,
    annual_cost       NUMERIC,
    currency          TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_contracts_partner ON alice.doc_contracts(contract_partner);

-- 18.4 RLS: only the service database user writes these tables; role checks happen in the
-- read tools (PROJ-128)
ALTER TABLE alice.doc_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_invoice_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_bank_statements ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_bank_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_security_settlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_contracts ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['doc_documents', 'doc_invoices', 'doc_invoice_line_items', 'doc_bank_statements',
                             'doc_bank_transactions', 'doc_security_settlements', 'doc_contracts'] LOOP
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
