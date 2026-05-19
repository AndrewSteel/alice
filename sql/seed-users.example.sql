-- ============================================================
-- ALICE - Seed Users (EXAMPLE / TEMPLATE)
-- ============================================================
-- Kopiere diese Datei nach sql/seed-users.sql und passe die
-- Werte an. seed-users.sql ist in .gitignore und gehört NICHT
-- ins Repository.
--
-- Ausführung NACH init-schema.sql:
--   psql -U <user> -d <database> -f sql/seed-users.sql
--
-- Oder via Docker:
--   docker exec -i postgres psql -U user -d alice < sql/seed-users.sql
-- ============================================================

-- ============================================================
-- 1. USER ERSTELLEN
-- ============================================================

INSERT INTO alice.users (username, display_name, email, role) VALUES
    ('admin',   'Admin User',  NULL, 'admin'),
    ('user1',   'User One',    NULL, 'user'),
    ('guest',   'Guest',       NULL, 'guest')
ON CONFLICT (username) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    role         = EXCLUDED.role;

-- ============================================================
-- 2. BERECHTIGUNGEN AUS TEMPLATES INITIALISIEREN
-- ============================================================

DO $$
DECLARE
    v_user RECORD;
BEGIN
    FOR v_user IN SELECT id, role FROM alice.users LOOP
        PERFORM alice.init_user_permissions(v_user.id, v_user.role);
        RAISE NOTICE 'Berechtigungen für % (%) initialisiert', v_user.id, v_user.role;
    END LOOP;
END $$;

-- ============================================================
-- 3. USER-PROFILE ERSTELLEN
-- ============================================================

INSERT INTO alice.user_profiles (user_id, facts, preferences) VALUES
(
    'admin',
    '{
        "name": "Admin User",
        "rolle": "Administrator",
        "interessen": ["Smart Home", "KI"]
    }',
    '{
        "sprache": "deutsch",
        "anrede": "du",
        "detailgrad": "technisch"
    }'
),
(
    'user1',
    '{
        "name": "User One",
        "rolle": "Bewohner",
        "interessen": ["Musik", "Kochen"]
    }',
    '{
        "sprache": "deutsch",
        "anrede": "du",
        "detailgrad": "normal"
    }'
),
(
    'guest',
    '{
        "name": "Gast",
        "rolle": "Besucher"
    }',
    '{
        "sprache": "deutsch",
        "anrede": "Sie",
        "detailgrad": "einfach"
    }'
)
ON CONFLICT (user_id) DO UPDATE SET
    facts        = EXCLUDED.facts,
    preferences  = EXCLUDED.preferences,
    last_updated = NOW();

-- ============================================================
-- 4. CUSTOM PERMISSION OVERRIDES (optional)
-- ============================================================
-- Individuelle Anpassungen, die von den Rollen-Templates abweichen.

-- Beispiel: user1 darf Kontoauszüge lesen (in der 'user'-Rolle standardmäßig gesperrt)
-- UPDATE alice.permissions_dms
-- SET can_read = TRUE, can_download = TRUE
-- WHERE user_id = (SELECT id FROM alice.users WHERE username = 'user1')
--   AND doc_type = 'BankStatement';

-- Beispiel: Gast darf zusätzlich im Esszimmer Licht steuern
-- UPDATE alice.permissions_home_assistant
-- SET allowed_areas = '["wohnzimmer", "gaestezimmer", "flur", "esszimmer"]'::jsonb
-- WHERE user_id = (SELECT id FROM alice.users WHERE username = 'guest')
--   AND domain = 'light';

-- ============================================================
-- 5. VERIFIZIERUNG
-- ============================================================

SELECT
    username,
    display_name,
    role,
    is_active,
    created_at
FROM alice.users
ORDER BY role, username;

SELECT * FROM alice.v_user_permissions_summary;
