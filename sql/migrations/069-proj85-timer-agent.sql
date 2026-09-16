-- ============================================================
-- Migration 069 — PROJ-85: Timer-Agent.
--
-- Adds:
--   1. alice.system_settings         — global key/value settings (new; first
--                                      consumer is timer_default_role)
--   2. alice.timers                  — one row per timer (state, owner role,
--                                      expiry, origin channel)
--   3. Timer columns on alice.role_templates.assistant_permissions (JSON keys)
--      and a can_use_timers flag on alice.permissions_assistant
--   4. alice.init_user_permissions() — copies the new can_use_timers flag
--   5. Timer intent templates in alice.ha_intent_templates (entity-less,
--      domain 'timer'); alice-ha-sync ignores them (no HA entity), so they
--      are seeded straight into Weaviate by scripts/seed-timer-intents.sh
--
-- Apply against the alice database after init-schema.sql.
-- Safe to re-run (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / idempotent
-- jsonb merge / ON CONFLICT DO UPDATE).
-- ============================================================

-- ------------------------------------------------------------
-- 1. System settings (global key/value)
-- ------------------------------------------------------------
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

-- ------------------------------------------------------------
-- 2. alice.timers
-- ------------------------------------------------------------
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
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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

ALTER TABLE alice.timers ENABLE ROW LEVEL SECURITY;
-- The chat-stream service connects as the schema owner and scopes every
-- query by owner_role itself (same pattern as alice.ha_entities). A single
-- permissive policy keeps RLS enabled without a second enforcement layer.
DROP POLICY IF EXISTS timers_allow_all ON alice.timers;
CREATE POLICY timers_allow_all ON alice.timers
    FOR ALL USING (TRUE) WITH CHECK (TRUE);

-- ------------------------------------------------------------
-- 3. Timer permission flag + role-template limits
-- ------------------------------------------------------------
ALTER TABLE alice.permissions_assistant
    ADD COLUMN IF NOT EXISTS can_use_timers BOOLEAN DEFAULT TRUE;

-- Role-template defaults (spec table). The three timer keys live inside the
-- existing assistant_permissions JSON blob, like the other assistant flags.
--   admin : on,  20 timers, 24 h
--   user  : on,  10 timers, 24 h
--   child : on,   3 timers,  2 h
--   guest : off
UPDATE alice.role_templates
SET assistant_permissions = assistant_permissions
    || '{"can_use_timers": true, "timer_max_active": 20, "timer_max_duration_seconds": 86400}'::jsonb
WHERE role = 'admin';

UPDATE alice.role_templates
SET assistant_permissions = assistant_permissions
    || '{"can_use_timers": true, "timer_max_active": 10, "timer_max_duration_seconds": 86400}'::jsonb
WHERE role = 'user';

UPDATE alice.role_templates
SET assistant_permissions = assistant_permissions
    || '{"can_use_timers": true, "timer_max_active": 3, "timer_max_duration_seconds": 7200}'::jsonb
WHERE role = 'child';

UPDATE alice.role_templates
SET assistant_permissions = assistant_permissions
    || '{"can_use_timers": false, "timer_max_active": 0, "timer_max_duration_seconds": 0}'::jsonb
WHERE role = 'guest';

-- Backfill existing users' can_use_timers from their role template.
UPDATE alice.permissions_assistant pa
SET can_use_timers = COALESCE(
        (rt.assistant_permissions->>'can_use_timers')::boolean, TRUE
    ),
    updated_at = NOW()
FROM alice.users u
JOIN alice.role_templates rt ON rt.role = u.role
WHERE pa.user_id = u.id;

-- ------------------------------------------------------------
-- 4. init_user_permissions() — carry the new flag on user creation
-- ------------------------------------------------------------
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
        can_use_timers
    ) VALUES (
        p_user_id,
        COALESCE((v_template.assistant_permissions->>'can_use_chat')::boolean,   true),
        COALESCE((v_template.assistant_permissions->>'can_use_voice')::boolean,  true),
        COALESCE((v_template.assistant_permissions->>'can_use_tools')::boolean,  true),
        COALESCE(v_template.assistant_permissions->'tools_allowed', '["*"]'::jsonb),
        COALESCE(v_template.assistant_permissions->'tools_denied',  '[]'::jsonb),
        (v_template.assistant_permissions->>'max_messages_per_day')::int,
        COALESCE((v_template.assistant_permissions->>'can_access_shared_memory')::boolean, false),
        COALESCE((v_template.assistant_permissions->>'can_use_timers')::boolean, true)
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
        updated_at               = NOW();
END;
$$ LANGUAGE plpgsql;

-- ------------------------------------------------------------
-- 5. Timer intent templates (entity-less, domain 'timer')
--    alice-ha-sync skips them (no HA entity); scripts/seed-timer-intents.sh
--    writes the patterns verbatim into the Weaviate HAIntent collection as the
--    vectorised utterance. So the patterns MUST be concrete natural sentences
--    with NO {value}/{name} placeholders — the duration / clock / name / delta
--    is re-extracted from the live transcript in app/timers.py after the
--    semantic match. Several phrasings per intent so the vector space covers
--    the ways a timer command is actually spoken.
-- ------------------------------------------------------------
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

-- Reporting only.
SELECT key, value FROM alice.system_settings WHERE key = 'timer_default_role';
SELECT role, assistant_permissions->'can_use_timers' AS can_use_timers,
       assistant_permissions->'timer_max_active' AS max_active,
       assistant_permissions->'timer_max_duration_seconds' AS max_duration
FROM alice.role_templates ORDER BY role;
