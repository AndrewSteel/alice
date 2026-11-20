-- ============================================================
-- PROJ-121: Household role model (admin / haushalt / guest)
--
-- - role 'user'  -> 'haushalt', role 'child' -> 'guest'
--   (alice.users.role, alice.timers.owner_role, role templates,
--    system setting timer_default_role)
-- - former 'child' users get the 'guest' template permissions
-- - removes per-doc-type DMS permissions (alice.permissions_dms,
--   alice.check_dms_permission) and per-user mailbox access
--   (alice.imap_mailbox_access)
--
-- Idempotent: a second run changes nothing and does not fail.
--   docker exec -i postgres psql -U <user> -d alice -v ON_ERROR_STOP=1 \
--     < sql/migrations/2026-11-20_PROJ-121_rollenmodell-haushalt.sql
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. Drop per-doc-type DMS permissions and per-user mailbox access
-- ------------------------------------------------------------
DROP VIEW IF EXISTS alice.v_dms_permissions;
-- Recreated below without the dms_readable_types column.
DROP VIEW IF EXISTS alice.v_user_permissions_summary;

DROP FUNCTION IF EXISTS alice.check_dms_permission(UUID, VARCHAR, VARCHAR, VARCHAR, DECIMAL);
DROP TABLE IF EXISTS alice.permissions_dms;
DROP TABLE IF EXISTS alice.imap_mailbox_access;

-- ------------------------------------------------------------
-- 2. Users: new role constraint, rename roles
-- ------------------------------------------------------------
ALTER TABLE alice.users DROP CONSTRAINT IF EXISTS users_role_check;

-- Remember former child users (permissions are reset to 'guest' below).
CREATE TEMP TABLE proj121_former_children ON COMMIT DROP AS
    SELECT id FROM alice.users WHERE role = 'child';

UPDATE alice.users SET role = 'haushalt' WHERE role = 'user';
UPDATE alice.users SET role = 'guest'    WHERE role = 'child';

ALTER TABLE alice.users ALTER COLUMN role SET DEFAULT 'haushalt';
ALTER TABLE alice.users
    ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'haushalt', 'guest'));

-- ------------------------------------------------------------
-- 3. Timers keep their owner (role scope)
-- ------------------------------------------------------------
ALTER TABLE alice.timers DROP CONSTRAINT IF EXISTS timers_owner_role_check;
UPDATE alice.timers SET owner_role = 'haushalt' WHERE owner_role = 'user';
UPDATE alice.timers SET owner_role = 'guest'    WHERE owner_role = 'child';
ALTER TABLE alice.timers
    ADD CONSTRAINT timers_owner_role_check CHECK (owner_role IN ('admin', 'haushalt', 'guest'));

-- Default role for timers of unrecognised speakers
UPDATE alice.system_settings SET value = '"haushalt"'::jsonb
WHERE key = 'timer_default_role' AND value = '"user"'::jsonb;
UPDATE alice.system_settings SET value = '"guest"'::jsonb
WHERE key = 'timer_default_role' AND value = '"child"'::jsonb;

-- ------------------------------------------------------------
-- 4. Role templates: 'haushalt' takes over all values of 'user'
--    (including admin changes to calendar / lists / timer settings)
-- ------------------------------------------------------------
ALTER TABLE alice.role_templates DROP COLUMN IF EXISTS dms_permissions;

INSERT INTO alice.role_templates (role, description, ha_permissions, system_permissions, assistant_permissions)
SELECT 'haushalt',
       'Haushaltsmitglied: alle Dokumente, Mails, Bilder; keine Verwaltung',
       ha_permissions, system_permissions, assistant_permissions
FROM alice.role_templates
WHERE role = 'user'
ON CONFLICT (role) DO NOTHING;

-- Household members may use every document, image and mail search tool.
UPDATE alice.role_templates
SET assistant_permissions = jsonb_set(
        assistant_permissions,
        '{tools_allowed}',
        (SELECT COALESCE(jsonb_agg(DISTINCT t), '[]'::jsonb)
         FROM jsonb_array_elements_text(
                  COALESCE(assistant_permissions->'tools_allowed', '[]'::jsonb)
                  || '["search_documents", "get_document_details", "search_images", "search_emails", "get_email_body"]'::jsonb
              ) AS t)
    )
WHERE role = 'haushalt'
  AND NOT (COALESCE(assistant_permissions->'tools_allowed', '[]'::jsonb) ? '*')
  AND NOT (COALESCE(assistant_permissions->'tools_allowed', '[]'::jsonb)
           @> '["search_documents", "get_document_details", "search_images", "search_emails", "get_email_body"]'::jsonb);

DELETE FROM alice.role_templates WHERE role IN ('user', 'child');

-- ------------------------------------------------------------
-- 5. Permission helper without the DMS part
-- ------------------------------------------------------------
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

-- ------------------------------------------------------------
-- 6. Former child users: restrictive 'guest' rights, no leftover
--    child-only HA domains (runs only in the first migration)
-- ------------------------------------------------------------
DELETE FROM alice.permissions_home_assistant
WHERE user_id IN (SELECT id FROM proj121_former_children);

SELECT alice.init_user_permissions(id, 'guest') FROM proj121_former_children;

-- ------------------------------------------------------------
-- 7. Overview view without the DMS column
-- ------------------------------------------------------------
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

COMMIT;
