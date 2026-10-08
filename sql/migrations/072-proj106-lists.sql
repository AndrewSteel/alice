-- ============================================================
-- Migration 072 — PROJ-106: Aufgaben- & Listen-Verwaltung (lokal).
--
-- Adds:
--   1. alice.lists            — private (owner only) and shared lists; exactly
--                               one shared list may carry the shopping flag.
--   2. alice.list_items       — entries with optional due / deadline (each a
--                               timestamp plus "has time" flag), priority, note,
--                               done state (when / by whom).
--   3. alice.list_preferences — the user's default list.
--   4. can_use_lists flag on alice.permissions_assistant and the
--      role_templates.assistant_permissions JSON (admin, user, child on;
--      guest off), backfilled for existing users.
--   5. alice.init_user_permissions() — copies the new flag on user creation.
--   6. Seed: the shared, flagged "Einkaufsliste".
--
-- Apply against the alice database after 071-proj87-calendar-agent.sql.
-- Safe to re-run (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / idempotent
-- jsonb merge / CREATE OR REPLACE / guarded seed).
-- ============================================================

-- ------------------------------------------------------------
-- 1. Lists
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alice.lists (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 100),
    is_shared   BOOLEAN NOT NULL DEFAULT FALSE,
    -- Private lists only: the single user who may see / change them. Deleting
    -- the user deletes his private lists.
    owner_id    UUID REFERENCES alice.users(id) ON DELETE CASCADE,
    -- Creator (shared lists: may rename / delete besides admin). Deleting the
    -- user keeps his shared lists; afterwards only admin is responsible.
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
-- 2. List items
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
-- 3. Default list per user
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

-- ------------------------------------------------------------
-- 4. Lists permission flag
-- ------------------------------------------------------------
ALTER TABLE alice.permissions_assistant
    ADD COLUMN IF NOT EXISTS can_use_lists BOOLEAN DEFAULT FALSE;

UPDATE alice.role_templates
SET assistant_permissions = assistant_permissions || '{"can_use_lists": true}'::jsonb
WHERE role IN ('admin', 'user', 'child')
  AND NOT (assistant_permissions ? 'can_use_lists');

UPDATE alice.role_templates
SET assistant_permissions = assistant_permissions || '{"can_use_lists": false}'::jsonb
WHERE role = 'guest'
  AND NOT (assistant_permissions ? 'can_use_lists');

-- Backfill existing users from their role template.
UPDATE alice.permissions_assistant pa
SET can_use_lists = COALESCE(
        (rt.assistant_permissions->>'can_use_lists')::boolean, FALSE
    ),
    updated_at = NOW()
FROM alice.users u
JOIN alice.role_templates rt ON rt.role = u.role
WHERE pa.user_id = u.id;

-- ------------------------------------------------------------
-- 5. init_user_permissions() — carry the new flag on user creation
--    (body identical to migration 071 except for can_use_lists)
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

-- ------------------------------------------------------------
-- 6. Seed: the shared shopping list (only on first apply)
-- ------------------------------------------------------------
INSERT INTO alice.lists (name, is_shared, is_shopping)
SELECT 'Einkaufsliste', TRUE, TRUE
WHERE NOT EXISTS (SELECT 1 FROM alice.lists WHERE is_shopping)
  AND NOT EXISTS (SELECT 1 FROM alice.lists WHERE is_shared AND lower(btrim(name)) = 'einkaufsliste');
