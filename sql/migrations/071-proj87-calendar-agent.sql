-- ============================================================
-- Migration 071 — PROJ-87: Kalender-Agent.
--
-- Adds:
--   1. alice.calendar_selections   — which Google calendars of a connection the
--                                    user enabled for Alice, plus the single
--                                    default calendar per user. Only selection
--                                    metadata — no event data, no names.
--   2. can_use_calendar flag on alice.permissions_assistant and the
--      role_templates.assistant_permissions JSON (admin + user on,
--      guest + child off), backfilled for existing users.
--   3. alice.init_user_permissions() — copies the new flag on user creation.
--
-- Apply against the alice database after 070-proj86-google-connections.sql.
-- Safe to re-run (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / idempotent
-- jsonb merge / CREATE OR REPLACE).
-- ============================================================

-- ------------------------------------------------------------
-- 1. Calendar selection
-- ------------------------------------------------------------
-- Composite key target so a selection row can reference (connection, owner):
-- the selection's user_id is then guaranteed to be the connection's owner.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'google_connections_id_user_uniq'
    ) THEN
        ALTER TABLE alice.google_connections
            ADD CONSTRAINT google_connections_id_user_uniq UNIQUE (id, user_id);
    END IF;
END $$;

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

-- ------------------------------------------------------------
-- 2. Calendar permission flag
-- ------------------------------------------------------------
ALTER TABLE alice.permissions_assistant
    ADD COLUMN IF NOT EXISTS can_use_calendar BOOLEAN DEFAULT FALSE;

UPDATE alice.role_templates
SET assistant_permissions = assistant_permissions || '{"can_use_calendar": true}'::jsonb
WHERE role IN ('admin', 'user')
  AND NOT (assistant_permissions ? 'can_use_calendar');

UPDATE alice.role_templates
SET assistant_permissions = assistant_permissions || '{"can_use_calendar": false}'::jsonb
WHERE role IN ('guest', 'child')
  AND NOT (assistant_permissions ? 'can_use_calendar');

-- Backfill existing users from their role template.
UPDATE alice.permissions_assistant pa
SET can_use_calendar = COALESCE(
        (rt.assistant_permissions->>'can_use_calendar')::boolean, FALSE
    ),
    updated_at = NOW()
FROM alice.users u
JOIN alice.role_templates rt ON rt.role = u.role
WHERE pa.user_id = u.id;

-- ------------------------------------------------------------
-- 3. init_user_permissions() — carry the new flag on user creation
--    (body identical to migration 069 except for can_use_calendar)
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
        can_use_timers, can_use_calendar
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
        COALESCE((v_template.assistant_permissions->>'can_use_calendar')::boolean, false)
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
        updated_at               = NOW();
END;
$$ LANGUAGE plpgsql;
