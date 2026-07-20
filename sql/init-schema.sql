-- ============================================================
-- ALICE — Consolidated Database Schema
-- Version: Phase 1 Final
-- Sources: init-postgres.sql + ha-intent-infrastructure.sql
--          + migrations 007–013
--
-- Safe to re-run on a fresh database (uses IF NOT EXISTS).
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
    locked_until                TIMESTAMPTZ
);

-- Partial unique index: NULL emails do not conflict
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
    ON alice.users (email)
    WHERE email IS NOT NULL;

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

-- 2.2 DMS (final CHECK includes BankTransaction from migration 013)
CREATE TABLE IF NOT EXISTS alice.permissions_dms (
    id                  SERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    doc_type            VARCHAR(50) NOT NULL CHECK (doc_type IN (
                            'Invoice', 'BankStatement', 'BankTransaction',
                            'SecuritySettlement', 'Document', 'Email', 'Contract', '*'
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
    UNIQUE(user_id)
);

-- ============================================================
-- 3. ROLE TEMPLATES
-- Final state after migrations 010 (English doc types) and
-- 013 (BankTransaction added to user role).
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
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["*"]}'
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
        {"doc_type": "BankStatement",      "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false},
        {"doc_type": "BankTransaction",    "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false},
        {"doc_type": "SecuritySettlement", "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false}
    ]',
    '{"can_manage_users": false, "can_manage_devices": false, "can_view_logs": false, "can_manage_workflows": false, "can_access_api_docs": false, "can_manage_memory": true, "can_delete_memory": false, "can_manage_dms_folders": false, "can_view_chat_archive": false, "can_manage_mailboxes": false}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant", "search_documents", "remember", "recall"]}'
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
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant"], "max_messages_per_day": 50}'
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
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant"], "max_messages_per_day": 20}'
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
        tools_allowed, tools_denied, max_messages_per_day, can_access_shared_memory
    ) VALUES (
        p_user_id,
        COALESCE((v_template.assistant_permissions->>'can_use_chat')::boolean,   true),
        COALESCE((v_template.assistant_permissions->>'can_use_voice')::boolean,  true),
        COALESCE((v_template.assistant_permissions->>'can_use_tools')::boolean,  true),
        COALESCE(v_template.assistant_permissions->'tools_allowed', '["*"]'::jsonb),
        COALESCE(v_template.assistant_permissions->'tools_denied',  '[]'::jsonb),
        (v_template.assistant_permissions->>'max_messages_per_day')::int,
        COALESCE((v_template.assistant_permissions->>'can_access_shared_memory')::boolean, false)
    )
    ON CONFLICT (user_id) DO UPDATE SET
        can_use_chat             = EXCLUDED.can_use_chat,
        can_use_voice            = EXCLUDED.can_use_voice,
        can_use_tools            = EXCLUDED.can_use_tools,
        tools_allowed            = EXCLUDED.tools_allowed,
        tools_denied             = EXCLUDED.tools_denied,
        max_messages_per_day     = EXCLUDED.max_messages_per_day,
        can_access_shared_memory = EXCLUDED.can_access_shared_memory,
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
-- user_id is UUID with FK (migration 008); title added in migration 008
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
    -- PROJ-51: chat storage classification & retention (migration 014)
    session_type  TEXT NOT NULL DEFAULT 'llm' CHECK (session_type IN ('llm', 'ha_only')),
    expires_at    TIMESTAMPTZ,
    source        TEXT CHECK (source IS NULL OR source IN ('webapp_cc', 'webapp_mic', 'esphome') OR source LIKE 'esphome:%')
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON alice.sessions(user_id, last_activity DESC);

-- PROJ-51: cleanup index for expired ha_only sessions (migration 014)
CREATE INDEX IF NOT EXISTS idx_sessions_cleanup
    ON alice.sessions(session_type, expires_at)
    WHERE session_type = 'ha_only' AND expires_at IS NOT NULL;

ALTER TABLE alice.sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sessions_allow_all ON alice.sessions;
CREATE POLICY sessions_allow_all ON alice.sessions
    FOR ALL USING (true) WITH CHECK (true);

-- Per-message storage (Tier 1 working memory)
-- user_id and session_id are UUID FKs (migration 008)
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
    -- PROJ-51: display-type for session restore (migration 014)
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
-- sort_order added in migration 012
CREATE TABLE IF NOT EXISTS alice.dms_watched_folders (
    id             SERIAL PRIMARY KEY,
    path           TEXT NOT NULL UNIQUE CHECK (char_length(path) <= 500),
    suggested_type TEXT CHECK (suggested_type IN (
                       'Invoice', 'BankStatement', 'Document', 'Email',
                       'SecuritySettlement', 'Contract'
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
