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

    role                        VARCHAR(20) DEFAULT 'user'
                                    CHECK (role IN ('admin', 'user', 'guest', 'child')),
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

-- 2.2 DMS
CREATE TABLE IF NOT EXISTS alice.permissions_dms (
    id                  SERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    doc_type            VARCHAR(50) NOT NULL CHECK (doc_type IN (
                            'Invoice', 'BankStatement', 'BankTransaction',
                            'SecuritySettlement', 'Document', 'Email', 'Contract', 'Image', '*'
                        )),
    can_read            BOOLEAN DEFAULT FALSE,
    can_create          BOOLEAN DEFAULT FALSE,
    can_update          BOOLEAN DEFAULT FALSE,
    can_delete          BOOLEAN DEFAULT FALSE,
    can_download        BOOLEAN DEFAULT FALSE,
    filter_own_only     BOOLEAN DEFAULT FALSE,
    allowed_categories  JSONB DEFAULT NULL,
    max_amount_visible  DECIMAL(12,2) DEFAULT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, doc_type)
);

CREATE INDEX IF NOT EXISTS idx_perm_dms_user ON alice.permissions_dms(user_id);
CREATE INDEX IF NOT EXISTS idx_perm_dms_type ON alice.permissions_dms(doc_type);

-- 2.3 System
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

-- 2.4 Assistant
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
    dms_permissions         JSONB NOT NULL,
    system_permissions      JSONB NOT NULL,
    assistant_permissions   JSONB NOT NULL
);

INSERT INTO alice.role_templates
    (role, description, ha_permissions, dms_permissions, system_permissions, assistant_permissions)
VALUES
(
    'admin',
    'Vollzugriff auf alle Funktionen',
    '[{"domain": "*", "can_read": true, "can_control": true}]',
    '[{"doc_type": "*", "can_read": true, "can_create": true, "can_update": true, "can_delete": true, "can_download": true}]',
    '{"can_manage_users": true, "can_manage_devices": true, "can_view_logs": true, "can_manage_workflows": true, "can_access_api_docs": true, "can_manage_memory": true, "can_delete_memory": true, "can_manage_dms_folders": true, "can_view_chat_archive": true, "can_manage_mailboxes": true}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["*"], "can_use_timers": true, "timer_max_active": 20, "timer_max_duration_seconds": 86400, "can_use_calendar": true, "can_use_lists": true}'
),
(
    'user',
    'Standard-Benutzer mit eingeschränkten Rechten',
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
    '[
        {"doc_type": "Invoice",            "can_read": true,  "can_create": true,  "can_update": false, "can_delete": false, "can_download": true},
        {"doc_type": "Document",           "can_read": true,  "can_create": true,  "can_update": false, "can_delete": false, "can_download": true},
        {"doc_type": "Email",              "can_read": true,  "can_create": false, "can_update": false, "can_delete": false, "can_download": false},
        {"doc_type": "Image",              "can_read": true,  "can_create": false, "can_update": false, "can_delete": false, "can_download": false},
        {"doc_type": "BankStatement",      "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false},
        {"doc_type": "BankTransaction",    "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false},
        {"doc_type": "SecuritySettlement", "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false}
    ]',
    '{"can_manage_users": false, "can_manage_devices": false, "can_view_logs": false, "can_manage_workflows": false, "can_access_api_docs": false, "can_manage_memory": true, "can_delete_memory": false, "can_manage_dms_folders": false, "can_view_chat_archive": false, "can_manage_mailboxes": false}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant", "search_documents", "search_images", "remember", "recall"], "can_use_timers": true, "timer_max_active": 10, "timer_max_duration_seconds": 86400, "can_use_calendar": true, "can_use_lists": true}'
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
    '[{"doc_type": "*", "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false}]',
    '{"can_manage_users": false, "can_manage_devices": false, "can_view_logs": false, "can_manage_workflows": false, "can_access_api_docs": false, "can_manage_memory": false, "can_delete_memory": false, "can_manage_dms_folders": false, "can_view_chat_archive": false, "can_manage_mailboxes": false}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant"], "max_messages_per_day": 50, "can_use_timers": false, "timer_max_active": 0, "timer_max_duration_seconds": 0, "can_use_calendar": false, "can_use_lists": false}'
),
(
    'child',
    'Kindersicherer Zugang mit Zeitbeschränkungen',
    '[
        {"domain": "light",        "can_read": true, "can_control": true, "allowed_areas": ["kinderzimmer"], "time_restrictions": {"allowed_hours": {"start": "07:00", "end": "20:00"}}},
        {"domain": "media_player", "can_read": true, "can_control": true, "allowed_areas": ["kinderzimmer"], "time_restrictions": {"allowed_hours": {"start": "14:00", "end": "19:00"}}},
        {"domain": "sensor",       "can_read": true, "can_control": false}
    ]',
    '[{"doc_type": "*", "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false}]',
    '{"can_manage_users": false, "can_manage_devices": false, "can_view_logs": false, "can_manage_workflows": false, "can_access_api_docs": false, "can_manage_memory": false, "can_delete_memory": false, "can_manage_dms_folders": false, "can_view_chat_archive": false, "can_manage_mailboxes": false}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant"], "max_messages_per_day": 20, "can_use_timers": true, "timer_max_active": 3, "timer_max_duration_seconds": 7200, "can_use_calendar": false, "can_use_lists": true}'
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
    v_dms_perm JSONB;
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

    -- DMS permissions
    FOR v_dms_perm IN SELECT * FROM jsonb_array_elements(v_template.dms_permissions)
    LOOP
        INSERT INTO alice.permissions_dms (
            user_id, doc_type,
            can_read, can_create, can_update, can_delete, can_download,
            filter_own_only, allowed_categories, max_amount_visible
        ) VALUES (
            p_user_id,
            v_dms_perm->>'doc_type',
            COALESCE((v_dms_perm->>'can_read')::boolean,     false),
            COALESCE((v_dms_perm->>'can_create')::boolean,   false),
            COALESCE((v_dms_perm->>'can_update')::boolean,   false),
            COALESCE((v_dms_perm->>'can_delete')::boolean,   false),
            COALESCE((v_dms_perm->>'can_download')::boolean, false),
            COALESCE((v_dms_perm->>'filter_own_only')::boolean, false),
            v_dms_perm->'allowed_categories',
            (v_dms_perm->>'max_amount_visible')::decimal
        )
        ON CONFLICT (user_id, doc_type) DO UPDATE SET
            can_read           = EXCLUDED.can_read,
            can_create         = EXCLUDED.can_create,
            can_update         = EXCLUDED.can_update,
            can_delete         = EXCLUDED.can_delete,
            can_download       = EXCLUDED.can_download,
            filter_own_only    = EXCLUDED.filter_own_only,
            allowed_categories = EXCLUDED.allowed_categories,
            max_amount_visible = EXCLUDED.max_amount_visible,
            updated_at         = NOW();
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

-- Check whether a user may perform a DMS action
CREATE OR REPLACE FUNCTION alice.check_dms_permission(
    p_user_id  UUID,
    p_doc_type VARCHAR(50),
    p_action   VARCHAR(20),   -- 'read', 'create', 'update', 'delete', 'download'
    p_category VARCHAR(100)  DEFAULT NULL,
    p_amount   DECIMAL       DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_perm          alice.permissions_dms%ROWTYPE;
    v_wildcard_perm alice.permissions_dms%ROWTYPE;
BEGIN
    SELECT * INTO v_perm
    FROM alice.permissions_dms
    WHERE user_id = p_user_id AND doc_type = p_doc_type;

    IF NOT FOUND THEN
        SELECT * INTO v_wildcard_perm
        FROM alice.permissions_dms
        WHERE user_id = p_user_id AND doc_type = '*';
        IF NOT FOUND THEN RETURN FALSE; END IF;
        v_perm := v_wildcard_perm;
    END IF;

    CASE p_action
        WHEN 'read'     THEN IF NOT v_perm.can_read     THEN RETURN FALSE; END IF;
        WHEN 'create'   THEN IF NOT v_perm.can_create   THEN RETURN FALSE; END IF;
        WHEN 'update'   THEN IF NOT v_perm.can_update   THEN RETURN FALSE; END IF;
        WHEN 'delete'   THEN IF NOT v_perm.can_delete   THEN RETURN FALSE; END IF;
        WHEN 'download' THEN IF NOT v_perm.can_download THEN RETURN FALSE; END IF;
        ELSE RETURN FALSE;
    END CASE;

    IF v_perm.allowed_categories IS NOT NULL AND p_category IS NOT NULL THEN
        IF NOT v_perm.allowed_categories ? p_category THEN RETURN FALSE; END IF;
    END IF;

    IF p_action = 'read' AND v_perm.max_amount_visible IS NOT NULL AND p_amount IS NOT NULL THEN
        IF p_amount > v_perm.max_amount_visible THEN RETURN FALSE; END IF;
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
    (SELECT COUNT(*) FROM alice.permissions_dms            WHERE user_id = u.id AND can_read    = TRUE) AS dms_readable_types,
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

CREATE OR REPLACE VIEW alice.v_dms_permissions AS
SELECT
    u.username,
    pdms.doc_type,
    pdms.can_read,
    pdms.can_create,
    pdms.can_update,
    pdms.can_delete,
    pdms.can_download,
    pdms.allowed_categories
FROM alice.permissions_dms pdms
JOIN alice.users u ON pdms.user_id = u.id
ORDER BY u.username, pdms.doc_type;

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
-- Shipping value 'user' (per spec); an admin can change it in Settings.
INSERT INTO alice.system_settings (key, value, description)
VALUES (
    'timer_default_role',
    '"user"'::jsonb,
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
                                 CHECK (owner_role IN ('admin', 'user', 'guest', 'child')),
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
-- Per-user mailbox access
CREATE TABLE IF NOT EXISTS alice.imap_mailbox_access (
    mailbox_id  UUID NOT NULL REFERENCES alice.imap_mailboxes(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    granted_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (mailbox_id, user_id)
);

ALTER TABLE alice.imap_mailbox_access ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS imap_access_select ON alice.imap_mailbox_access;
CREATE POLICY imap_access_select ON alice.imap_mailbox_access FOR SELECT USING (TRUE);
DROP POLICY IF EXISTS imap_access_insert ON alice.imap_mailbox_access;
CREATE POLICY imap_access_insert ON alice.imap_mailbox_access FOR INSERT WITH CHECK (TRUE);
DROP POLICY IF EXISTS imap_access_update ON alice.imap_mailbox_access;
CREATE POLICY imap_access_update ON alice.imap_mailbox_access FOR UPDATE USING (TRUE);
DROP POLICY IF EXISTS imap_access_delete ON alice.imap_mailbox_access;
CREATE POLICY imap_access_delete ON alice.imap_mailbox_access FOR DELETE USING (TRUE);

CREATE INDEX IF NOT EXISTS idx_imap_access_mailbox ON alice.imap_mailbox_access(mailbox_id);
CREATE INDEX IF NOT EXISTS idx_imap_access_user    ON alice.imap_mailbox_access(user_id);

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
