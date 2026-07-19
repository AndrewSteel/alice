#!/bin/bash
# ============================================================
# PROJ-65: Add three system-permission flags and backfill.
#
#   alice.permissions_system gains three BOOLEAN columns
#   (DEFAULT FALSE):
#     - can_manage_dms_folders
#     - can_view_chat_archive
#     - can_manage_mailboxes
#
#   alice.role_templates.system_permissions is updated so the
#   admin template carries all three flags = true and the
#   user/guest/child templates carry all three = false.
#
#   Existing users with role = 'admin' are retroactively set to
#   true on all three flags; every other existing user keeps the
#   FALSE default (no behaviour change).
# ============================================================
# Idempotent: ADD COLUMN IF NOT EXISTS, jsonb template rewrite,
# and re-setting admin rows to true are all safe to repeat.
#
# Usage:
#   ./proj65-add-permission-flags.sh [CONTAINER] [DB_USER] [DB_NAME]
#   ./proj65-add-permission-flags.sh postgres user alice
# ============================================================
set -euo pipefail

CONTAINER="${1:-postgres}"
DB_USER="${2:-user}"
DB_NAME="${3:-alice}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

psql_run() {
    docker exec -i "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 "$@"
}

echo "============================================================"
echo "PROJ-65: add permissions_system flags + admin backfill"
echo "============================================================"
echo "Container: ${CONTAINER}   DB: ${DB_NAME}   User: ${DB_USER}"
echo ""

# --- Existing admin users that WILL be backfilled to true ---------------
echo "Existing admin users to backfill (all three flags -> true):"
psql_run -c "
    SELECT u.id, u.username
    FROM alice.users u
    WHERE u.role = 'admin'
    ORDER BY u.username;
"

# --- Apply schema + template + backfill in a single transaction ---------
echo "Applying migration..."
admins=$(psql_run -t -A <<'SQL'
BEGIN;

-- 1. Add the three new columns (idempotent).
ALTER TABLE alice.permissions_system
    ADD COLUMN IF NOT EXISTS can_manage_dms_folders BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS can_view_chat_archive  BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS can_manage_mailboxes   BOOLEAN DEFAULT FALSE;

-- 2. Update role templates (idempotent merge of the three new keys).
--    admin -> true; user/guest/child -> false.
UPDATE alice.role_templates
SET system_permissions = system_permissions
    || '{"can_manage_dms_folders": true, "can_view_chat_archive": true, "can_manage_mailboxes": true}'::jsonb
WHERE role = 'admin';

UPDATE alice.role_templates
SET system_permissions = system_permissions
    || '{"can_manage_dms_folders": false, "can_view_chat_archive": false, "can_manage_mailboxes": false}'::jsonb
WHERE role IN ('user', 'guest', 'child');

-- 3. Backfill existing admin users' permission rows to true.
--    Non-admin users keep the FALSE default (untouched).
UPDATE alice.permissions_system ps
SET can_manage_dms_folders = TRUE,
    can_view_chat_archive  = TRUE,
    can_manage_mailboxes   = TRUE,
    updated_at             = NOW()
FROM alice.users u
WHERE ps.user_id = u.id
  AND u.role = 'admin';

-- Count of admin permission rows now fully set (for reporting only).
SELECT count(*)
FROM alice.permissions_system ps
JOIN alice.users u ON u.id = ps.user_id
WHERE u.role = 'admin'
  AND ps.can_manage_dms_folders
  AND ps.can_view_chat_archive
  AND ps.can_manage_mailboxes;

COMMIT;
SQL
)

echo ""
echo "------------------------------------------------------------"
echo -e "  Admin permission rows now fully set: ${GREEN}${admins}${NC}"
echo "------------------------------------------------------------"
echo -e "${GREEN}Migration complete.${NC}"
