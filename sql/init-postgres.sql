-- ============================================================
-- ALICE - PostgreSQL Schema mit feingranularen Berechtigungen
-- Version: 2.0
-- ============================================================

CREATE SCHEMA IF NOT EXISTS alice;

-- ============================================================
-- 1. USER MANAGEMENT
-- ============================================================

CREATE TABLE alice.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    email VARCHAR(255),
    
    -- Phase 1.5: Passwort-Auth
    password_hash VARCHAR(255),
    
    -- Phase 2: WebAuthn/Passkeys
    webauthn_credentials JSONB DEFAULT '[]',
    
    -- Phase 2: Speaker Recognition
    speaker_embeddings JSONB DEFAULT '[]',
    speaker_enrollment_complete BOOLEAN DEFAULT FALSE,
    
    -- Basis-Rolle (für schnelle Prüfungen)
    role VARCHAR(20) DEFAULT 'user' CHECK (role IN ('admin', 'user', 'guest', 'child')),
    
    -- Metadaten
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_login TIMESTAMPTZ,
    failed_login_attempts INT DEFAULT 0,
    locked_until TIMESTAMPTZ
);

-- ============================================================
-- 2. FEINGRANULARE BERECHTIGUNGEN
-- ============================================================

-- 2.1 Home Assistant Berechtigungen
-- Trennung: read (Sensoren lesen) vs. control (Geräte steuern)
-- Plus optionale Entity-Filter

CREATE TABLE alice.permissions_home_assistant (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    
    -- Domain (light, switch, climate, sensor, cover, media_player, etc.)
    domain VARCHAR(50) NOT NULL,
    
    -- Berechtigungstypen
    can_read BOOLEAN DEFAULT FALSE,      -- Status/Werte abfragen
    can_control BOOLEAN DEFAULT FALSE,   -- Steuern/Ändern
    
    -- Optionale Filter (NULL = alle erlaubt)
    -- Beispiel: ["wohnzimmer", "kueche"] oder ["light.schreibtisch"]
    allowed_areas JSONB DEFAULT NULL,    -- Räume/Bereiche
    allowed_entities JSONB DEFAULT NULL, -- Spezifische Entity-IDs
    denied_entities JSONB DEFAULT NULL,  -- Explizit verbotene Entities
    
    -- Zeitbasierte Einschränkungen (optional, für Phase 3)
    time_restrictions JSONB DEFAULT NULL,
    -- Beispiel: {"allowed_hours": {"start": "06:00", "end": "22:00"}, "days": ["mon","tue","wed","thu","fri","sat","sun"]}
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id, domain)
);

CREATE INDEX idx_perm_ha_user ON alice.permissions_home_assistant(user_id);
CREATE INDEX idx_perm_ha_domain ON alice.permissions_home_assistant(domain);

-- 2.2 DMS Berechtigungen
-- Pro Dokumenttyp separate Berechtigungen

CREATE TABLE alice.permissions_dms (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    
    -- Dokumenttyp (entspricht Weaviate Collections)
    doc_type VARCHAR(50) NOT NULL CHECK (doc_type IN (
        'Rechnung', 
        'Kontoauszug', 
        'WertpapierAbrechnung', 
        'Dokument', 
        'Email',
        'Vertrag',
        '*'  -- Wildcard für alle Typen
    )),
    
    -- Berechtigungstypen
    can_read BOOLEAN DEFAULT FALSE,       -- Dokumente suchen/anzeigen
    can_create BOOLEAN DEFAULT FALSE,     -- Neue Dokumente hinzufügen
    can_update BOOLEAN DEFAULT FALSE,     -- Metadaten ändern
    can_delete BOOLEAN DEFAULT FALSE,     -- Dokumente löschen
    can_download BOOLEAN DEFAULT FALSE,   -- Original-PDF herunterladen
    
    -- Optionale Filter
    -- Beispiel: Nur eigene Dokumente, nur bestimmte Kategorien
    filter_own_only BOOLEAN DEFAULT FALSE,  -- Nur selbst erstellte Dokumente
    allowed_categories JSONB DEFAULT NULL,  -- ["Energie", "Hardware", "Versicherung"]
    max_amount_visible DECIMAL(12,2) DEFAULT NULL,  -- Beträge über X ausblenden
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id, doc_type)
);

CREATE INDEX idx_perm_dms_user ON alice.permissions_dms(user_id);
CREATE INDEX idx_perm_dms_type ON alice.permissions_dms(doc_type);

-- 2.3 System/Settings Berechtigungen

CREATE TABLE alice.permissions_system (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    
    -- Berechtigungsbereiche
    can_manage_users BOOLEAN DEFAULT FALSE,
    can_manage_devices BOOLEAN DEFAULT FALSE,
    can_view_logs BOOLEAN DEFAULT FALSE,
    can_manage_workflows BOOLEAN DEFAULT FALSE,
    can_access_api_docs BOOLEAN DEFAULT FALSE,
    can_manage_memory BOOLEAN DEFAULT FALSE,  -- Eigenes Memory verwalten
    can_delete_memory BOOLEAN DEFAULT FALSE,  -- Memory anderer User löschen (Admin)
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id)
);

-- 2.4 Alice-spezifische Berechtigungen (Chat-Features)

CREATE TABLE alice.permissions_assistant (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    
    -- Chat-Features
    can_use_chat BOOLEAN DEFAULT TRUE,
    can_use_voice BOOLEAN DEFAULT TRUE,      -- Phase 2
    can_use_tools BOOLEAN DEFAULT TRUE,      -- Tool-Calling erlauben
    
    -- Spezifische Tools
    tools_allowed JSONB DEFAULT '["*"]',     -- ["home_assistant", "search_documents", "remember"]
    tools_denied JSONB DEFAULT '[]',         -- Explizit verbotene Tools
    
    -- Limits
    max_messages_per_day INT DEFAULT NULL,   -- NULL = unbegrenzt
    max_tokens_per_message INT DEFAULT NULL,
    
    -- Kontext-Zugriff
    can_access_shared_memory BOOLEAN DEFAULT FALSE,  -- Zugriff auf Family-Kontext
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id)
);

-- ============================================================
-- 3. VORDEFINIERTE ROLLEN-TEMPLATES
-- (Werden bei User-Erstellung als Vorlage genutzt)
-- ============================================================

CREATE TABLE alice.role_templates (
    role VARCHAR(20) PRIMARY KEY,
    description TEXT,
    ha_permissions JSONB NOT NULL,
    dms_permissions JSONB NOT NULL,
    system_permissions JSONB NOT NULL,
    assistant_permissions JSONB NOT NULL
);

INSERT INTO alice.role_templates (role, description, ha_permissions, dms_permissions, system_permissions, assistant_permissions) VALUES
(
    'admin',
    'Vollzugriff auf alle Funktionen',
    '[
        {"domain": "*", "can_read": true, "can_control": true}
    ]',
    '[
        {"doc_type": "*", "can_read": true, "can_create": true, "can_update": true, "can_delete": true, "can_download": true}
    ]',
    '{"can_manage_users": true, "can_manage_devices": true, "can_view_logs": true, "can_manage_workflows": true, "can_access_api_docs": true, "can_manage_memory": true, "can_delete_memory": true}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["*"]}'
),
(
    'user',
    'Standard-Benutzer mit eingeschränkten Rechten',
    '[
        {"domain": "light", "can_read": true, "can_control": true},
        {"domain": "switch", "can_read": true, "can_control": true},
        {"domain": "climate", "can_read": true, "can_control": true},
        {"domain": "sensor", "can_read": true, "can_control": false},
        {"domain": "media_player", "can_read": true, "can_control": true},
        {"domain": "cover", "can_read": true, "can_control": true},
        {"domain": "vacuum", "can_read": true, "can_control": true},
        {"domain": "alarm_control_panel", "can_read": true, "can_control": false}
    ]',
    '[
        {"doc_type": "Rechnung", "can_read": true, "can_create": true, "can_update": false, "can_delete": false, "can_download": true},
        {"doc_type": "Dokument", "can_read": true, "can_create": true, "can_update": false, "can_delete": false, "can_download": true},
        {"doc_type": "Email", "can_read": true, "can_create": false, "can_update": false, "can_delete": false, "can_download": false},
        {"doc_type": "Kontoauszug", "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false},
        {"doc_type": "WertpapierAbrechnung", "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false}
    ]',
    '{"can_manage_users": false, "can_manage_devices": false, "can_view_logs": false, "can_manage_workflows": false, "can_access_api_docs": false, "can_manage_memory": true, "can_delete_memory": false}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant", "search_documents", "remember", "recall"]}'
),
(
    'guest',
    'Eingeschränkter Gast-Zugang',
    '[
        {"domain": "light", "can_read": true, "can_control": true, "allowed_areas": ["wohnzimmer", "gaestezimmer", "flur"]},
        {"domain": "climate", "can_read": true, "can_control": false},
        {"domain": "sensor", "can_read": true, "can_control": false},
        {"domain": "media_player", "can_read": true, "can_control": true, "allowed_areas": ["wohnzimmer"]}
    ]',
    '[
        {"doc_type": "*", "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false}
    ]',
    '{"can_manage_users": false, "can_manage_devices": false, "can_view_logs": false, "can_manage_workflows": false, "can_access_api_docs": false, "can_manage_memory": false, "can_delete_memory": false}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant"], "max_messages_per_day": 50}'
),
(
    'child',
    'Kindersicherer Zugang mit Zeitbeschränkungen',
    '[
        {"domain": "light", "can_read": true, "can_control": true, "allowed_areas": ["kinderzimmer"], "time_restrictions": {"allowed_hours": {"start": "07:00", "end": "20:00"}}},
        {"domain": "media_player", "can_read": true, "can_control": true, "allowed_areas": ["kinderzimmer"], "time_restrictions": {"allowed_hours": {"start": "14:00", "end": "19:00"}}},
        {"domain": "sensor", "can_read": true, "can_control": false}
    ]',
    '[
        {"doc_type": "*", "can_read": false, "can_create": false, "can_update": false, "can_delete": false, "can_download": false}
    ]',
    '{"can_manage_users": false, "can_manage_devices": false, "can_view_logs": false, "can_manage_workflows": false, "can_access_api_docs": false, "can_manage_memory": false, "can_delete_memory": false}',
    '{"can_use_chat": true, "can_use_voice": true, "can_use_tools": true, "tools_allowed": ["home_assistant"], "max_messages_per_day": 20}'
);

-- ============================================================
-- 4. HELPER FUNCTIONS
-- ============================================================

-- Funktion: Berechtigungen für User aus Template initialisieren
CREATE OR REPLACE FUNCTION alice.init_user_permissions(
    p_user_id UUID,
    p_role VARCHAR(20)
) RETURNS VOID AS $$
DECLARE
    v_template alice.role_templates%ROWTYPE;
    v_ha_perm JSONB;
    v_dms_perm JSONB;
BEGIN
    -- Template laden
    SELECT * INTO v_template FROM alice.role_templates WHERE role = p_role;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Role template % not found', p_role;
    END IF;
    
    -- Home Assistant Berechtigungen
    FOR v_ha_perm IN SELECT * FROM jsonb_array_elements(v_template.ha_permissions)
    LOOP
        INSERT INTO alice.permissions_home_assistant (
            user_id, domain, can_read, can_control, 
            allowed_areas, allowed_entities, denied_entities, time_restrictions
        ) VALUES (
            p_user_id,
            v_ha_perm->>'domain',
            COALESCE((v_ha_perm->>'can_read')::boolean, false),
            COALESCE((v_ha_perm->>'can_control')::boolean, false),
            v_ha_perm->'allowed_areas',
            v_ha_perm->'allowed_entities',
            v_ha_perm->'denied_entities',
            v_ha_perm->'time_restrictions'
        )
        ON CONFLICT (user_id, domain) DO UPDATE SET
            can_read = EXCLUDED.can_read,
            can_control = EXCLUDED.can_control,
            allowed_areas = EXCLUDED.allowed_areas,
            allowed_entities = EXCLUDED.allowed_entities,
            denied_entities = EXCLUDED.denied_entities,
            time_restrictions = EXCLUDED.time_restrictions,
            updated_at = NOW();
    END LOOP;
    
    -- DMS Berechtigungen
    FOR v_dms_perm IN SELECT * FROM jsonb_array_elements(v_template.dms_permissions)
    LOOP
        INSERT INTO alice.permissions_dms (
            user_id, doc_type, can_read, can_create, can_update, can_delete, can_download,
            filter_own_only, allowed_categories, max_amount_visible
        ) VALUES (
            p_user_id,
            v_dms_perm->>'doc_type',
            COALESCE((v_dms_perm->>'can_read')::boolean, false),
            COALESCE((v_dms_perm->>'can_create')::boolean, false),
            COALESCE((v_dms_perm->>'can_update')::boolean, false),
            COALESCE((v_dms_perm->>'can_delete')::boolean, false),
            COALESCE((v_dms_perm->>'can_download')::boolean, false),
            COALESCE((v_dms_perm->>'filter_own_only')::boolean, false),
            v_dms_perm->'allowed_categories',
            (v_dms_perm->>'max_amount_visible')::decimal
        )
        ON CONFLICT (user_id, doc_type) DO UPDATE SET
            can_read = EXCLUDED.can_read,
            can_create = EXCLUDED.can_create,
            can_update = EXCLUDED.can_update,
            can_delete = EXCLUDED.can_delete,
            can_download = EXCLUDED.can_download,
            filter_own_only = EXCLUDED.filter_own_only,
            allowed_categories = EXCLUDED.allowed_categories,
            max_amount_visible = EXCLUDED.max_amount_visible,
            updated_at = NOW();
    END LOOP;
    
    -- System Berechtigungen
    INSERT INTO alice.permissions_system (
        user_id, 
        can_manage_users, can_manage_devices, can_view_logs, 
        can_manage_workflows, can_access_api_docs, can_manage_memory, can_delete_memory
    ) VALUES (
        p_user_id,
        COALESCE((v_template.system_permissions->>'can_manage_users')::boolean, false),
        COALESCE((v_template.system_permissions->>'can_manage_devices')::boolean, false),
        COALESCE((v_template.system_permissions->>'can_view_logs')::boolean, false),
        COALESCE((v_template.system_permissions->>'can_manage_workflows')::boolean, false),
        COALESCE((v_template.system_permissions->>'can_access_api_docs')::boolean, false),
        COALESCE((v_template.system_permissions->>'can_manage_memory')::boolean, false),
        COALESCE((v_template.system_permissions->>'can_delete_memory')::boolean, false)
    )
    ON CONFLICT (user_id) DO UPDATE SET
        can_manage_users = EXCLUDED.can_manage_users,
        can_manage_devices = EXCLUDED.can_manage_devices,
        can_view_logs = EXCLUDED.can_view_logs,
        can_manage_workflows = EXCLUDED.can_manage_workflows,
        can_access_api_docs = EXCLUDED.can_access_api_docs,
        can_manage_memory = EXCLUDED.can_manage_memory,
        can_delete_memory = EXCLUDED.can_delete_memory,
        updated_at = NOW();
    
    -- Assistant Berechtigungen
    INSERT INTO alice.permissions_assistant (
        user_id, 
        can_use_chat, can_use_voice, can_use_tools,
        tools_allowed, tools_denied, max_messages_per_day, can_access_shared_memory
    ) VALUES (
        p_user_id,
        COALESCE((v_template.assistant_permissions->>'can_use_chat')::boolean, true),
        COALESCE((v_template.assistant_permissions->>'can_use_voice')::boolean, true),
        COALESCE((v_template.assistant_permissions->>'can_use_tools')::boolean, true),
        COALESCE(v_template.assistant_permissions->'tools_allowed', '["*"]'::jsonb),
        COALESCE(v_template.assistant_permissions->'tools_denied', '[]'::jsonb),
        (v_template.assistant_permissions->>'max_messages_per_day')::int,
        COALESCE((v_template.assistant_permissions->>'can_access_shared_memory')::boolean, false)
    )
    ON CONFLICT (user_id) DO UPDATE SET
        can_use_chat = EXCLUDED.can_use_chat,
        can_use_voice = EXCLUDED.can_use_voice,
        can_use_tools = EXCLUDED.can_use_tools,
        tools_allowed = EXCLUDED.tools_allowed,
        tools_denied = EXCLUDED.tools_denied,
        max_messages_per_day = EXCLUDED.max_messages_per_day,
        can_access_shared_memory = EXCLUDED.can_access_shared_memory,
        updated_at = NOW();
        
END;
$$ LANGUAGE plpgsql;

-- Funktion: Prüft ob User eine HA-Aktion ausführen darf
CREATE OR REPLACE FUNCTION alice.check_ha_permission(
    p_user_id UUID,
    p_domain VARCHAR(50),
    p_entity_id VARCHAR(255),
    p_action VARCHAR(20),  -- 'read' oder 'control'
    p_area VARCHAR(100) DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_perm alice.permissions_home_assistant%ROWTYPE;
    v_wildcard_perm alice.permissions_home_assistant%ROWTYPE;
    v_has_permission BOOLEAN := FALSE;
BEGIN
    -- Erst spezifische Domain-Berechtigung prüfen
    SELECT * INTO v_perm 
    FROM alice.permissions_home_assistant 
    WHERE user_id = p_user_id AND domain = p_domain;
    
    -- Falls nicht gefunden, Wildcard prüfen
    IF NOT FOUND THEN
        SELECT * INTO v_wildcard_perm 
        FROM alice.permissions_home_assistant 
        WHERE user_id = p_user_id AND domain = '*';
        
        IF NOT FOUND THEN
            RETURN FALSE;
        END IF;
        v_perm := v_wildcard_perm;
    END IF;
    
    -- Basis-Berechtigung prüfen
    IF p_action = 'read' THEN
        v_has_permission := v_perm.can_read;
    ELSIF p_action = 'control' THEN
        v_has_permission := v_perm.can_control;
    END IF;
    
    IF NOT v_has_permission THEN
        RETURN FALSE;
    END IF;
    
    -- Entity explizit verboten?
    IF v_perm.denied_entities IS NOT NULL AND 
       v_perm.denied_entities ? p_entity_id THEN
        RETURN FALSE;
    END IF;
    
    -- Wenn allowed_entities gesetzt, muss Entity drin sein
    IF v_perm.allowed_entities IS NOT NULL AND 
       NOT v_perm.allowed_entities ? p_entity_id THEN
        RETURN FALSE;
    END IF;
    
    -- Wenn allowed_areas gesetzt und Area bekannt, muss Area drin sein
    IF v_perm.allowed_areas IS NOT NULL AND p_area IS NOT NULL THEN
        IF NOT v_perm.allowed_areas ? p_area THEN
            RETURN FALSE;
        END IF;
    END IF;
    
    -- Zeitbeschränkungen prüfen (vereinfacht)
    IF v_perm.time_restrictions IS NOT NULL THEN
        DECLARE
            v_start TIME;
            v_end TIME;
            v_now TIME := LOCALTIME;
        BEGIN
            v_start := (v_perm.time_restrictions->'allowed_hours'->>'start')::TIME;
            v_end := (v_perm.time_restrictions->'allowed_hours'->>'end')::TIME;
            
            IF v_now < v_start OR v_now > v_end THEN
                RETURN FALSE;
            END IF;
        EXCEPTION WHEN OTHERS THEN
            -- Bei Parse-Fehlern erlauben
            NULL;
        END;
    END IF;
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Funktion: Prüft ob User auf Dokumenttyp zugreifen darf
CREATE OR REPLACE FUNCTION alice.check_dms_permission(
    p_user_id UUID,
    p_doc_type VARCHAR(50),
    p_action VARCHAR(20),  -- 'read', 'create', 'update', 'delete', 'download'
    p_category VARCHAR(100) DEFAULT NULL,
    p_amount DECIMAL DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_perm alice.permissions_dms%ROWTYPE;
    v_wildcard_perm alice.permissions_dms%ROWTYPE;
BEGIN
    -- Erst spezifische Dokumenttyp-Berechtigung prüfen
    SELECT * INTO v_perm 
    FROM alice.permissions_dms 
    WHERE user_id = p_user_id AND doc_type = p_doc_type;
    
    -- Falls nicht gefunden, Wildcard prüfen
    IF NOT FOUND THEN
        SELECT * INTO v_wildcard_perm 
        FROM alice.permissions_dms 
        WHERE user_id = p_user_id AND doc_type = '*';
        
        IF NOT FOUND THEN
            RETURN FALSE;
        END IF;
        v_perm := v_wildcard_perm;
    END IF;
    
    -- Basis-Berechtigung prüfen
    CASE p_action
        WHEN 'read' THEN 
            IF NOT v_perm.can_read THEN RETURN FALSE; END IF;
        WHEN 'create' THEN 
            IF NOT v_perm.can_create THEN RETURN FALSE; END IF;
        WHEN 'update' THEN 
            IF NOT v_perm.can_update THEN RETURN FALSE; END IF;
        WHEN 'delete' THEN 
            IF NOT v_perm.can_delete THEN RETURN FALSE; END IF;
        WHEN 'download' THEN 
            IF NOT v_perm.can_download THEN RETURN FALSE; END IF;
        ELSE
            RETURN FALSE;
    END CASE;
    
    -- Kategorie-Filter
    IF v_perm.allowed_categories IS NOT NULL AND p_category IS NOT NULL THEN
        IF NOT v_perm.allowed_categories ? p_category THEN
            RETURN FALSE;
        END IF;
    END IF;
    
    -- Betrags-Filter (nur für read relevant)
    IF p_action = 'read' AND v_perm.max_amount_visible IS NOT NULL AND p_amount IS NOT NULL THEN
        IF p_amount > v_perm.max_amount_visible THEN
            RETURN FALSE;
        END IF;
    END IF;
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 5. INITIALE USER 
-- ============================================================
-- User und deren Daten werden separat in seed-users.sql angelegt.
-- Diese Datei gehört NICHT ins Git Repository!
--
-- Ausführung nach diesem Schema:
--   psql -U user -d alice -f seed-users.sql
-- ============================================================

-- ============================================================
-- 6. AUTH SESSIONS
-- ============================================================

CREATE TABLE alice.auth_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    device_info JSONB,
    ip_address INET,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_activity TIMESTAMPTZ DEFAULT NOW(),
    is_valid BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_auth_sessions_token ON alice.auth_sessions(token_hash) WHERE is_valid = TRUE;
CREATE INDEX idx_auth_sessions_user ON alice.auth_sessions(user_id, expires_at);

-- WebAuthn Challenges (Phase 2)
CREATE TABLE alice.webauthn_challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES alice.users(id) ON DELETE CASCADE,
    challenge TEXT NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('registration', 'authentication')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '5 minutes'),
    used BOOLEAN DEFAULT FALSE
);

-- ============================================================
-- 7. AGENT MEMORY TABELLEN
-- ============================================================

-- Aktive Konversationen
CREATE TABLE alice.messages (
    id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    tool_calls JSONB,
    tool_results JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    token_count INT,
    transferred_to_weaviate BOOLEAN DEFAULT FALSE,
    transferred_at TIMESTAMPTZ,
    weaviate_id UUID
);

CREATE INDEX idx_messages_session ON alice.messages(session_id, timestamp);
CREATE INDEX idx_messages_user_recent ON alice.messages(user_id, timestamp DESC);
CREATE INDEX idx_messages_not_transferred ON alice.messages(user_id) 
    WHERE transferred_to_weaviate = FALSE;

-- Session-Metadaten
CREATE TABLE alice.sessions (
    session_id UUID PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    last_activity TIMESTAMPTZ DEFAULT NOW(),
    message_count INT DEFAULT 0,
    summary TEXT,
    key_topics TEXT[],
    is_active BOOLEAN DEFAULT TRUE
);

-- User-Profile (Tier 3: Summarized Facts)
CREATE TABLE alice.user_profiles (
    user_id VARCHAR(255) PRIMARY KEY,
    facts JSONB DEFAULT '{}',
    preferences JSONB DEFAULT '{}',
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

-- Profile werden in seed-users.sql angelegt

-- ============================================================
-- 8. VIEWS FÜR EINFACHE ABFRAGEN
-- ============================================================

-- Übersicht aller User mit ihren Basis-Berechtigungen
CREATE OR REPLACE VIEW alice.v_user_permissions_summary AS
SELECT 
    u.username,
    u.display_name,
    u.role,
    u.is_active,
    (SELECT COUNT(*) FROM alice.permissions_home_assistant WHERE user_id = u.id AND can_control = TRUE) as ha_control_domains,
    (SELECT COUNT(*) FROM alice.permissions_dms WHERE user_id = u.id AND can_read = TRUE) as dms_readable_types,
    ps.can_manage_users,
    pa.max_messages_per_day
FROM alice.users u
LEFT JOIN alice.permissions_system ps ON u.id = ps.user_id
LEFT JOIN alice.permissions_assistant pa ON u.id = pa.user_id;

-- Detaillierte HA-Berechtigungen pro User
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

-- Detaillierte DMS-Berechtigungen pro User
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