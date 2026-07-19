#!/bin/bash
# ============================================================
# PROJ-63: Migrate alice.user_profiles.preferences.sprache
#          from word-form ("deutsch"/"englisch") to ISO 639-1
#          codes ("de"/"en").
# ============================================================
# Only exact matches on "deutsch"/"englisch" are rewritten.
# Anything else (null, already-migrated codes, unknown/manual
# values) is left untouched and logged as skipped.
#
# Usage:
#   ./proj63-migrate-sprache-codes.sh [CONTAINER] [DB_USER] [DB_NAME]
#   ./proj63-migrate-sprache-codes.sh postgres user alice
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
echo "PROJ-63: sprache word-form -> ISO code migration"
echo "============================================================"
echo "Container: ${CONTAINER}   DB: ${DB_NAME}   User: ${DB_USER}"
echo ""

# --- Rows that WILL be migrated -----------------------------------------
echo "Rows to migrate (deutsch -> de, englisch -> en):"
psql_run -c "
    SELECT user_id, preferences->>'sprache' AS sprache
    FROM alice.user_profiles
    WHERE preferences->>'sprache' IN ('deutsch', 'englisch')
    ORDER BY user_id;
"

# --- Rows that will be SKIPPED (has sprache, but not a word-form) --------
echo -e "${YELLOW}Rows skipped (sprache present but not deutsch/englisch — left unchanged):${NC}"
psql_run -c "
    SELECT user_id, preferences->>'sprache' AS sprache
    FROM alice.user_profiles
    WHERE preferences ? 'sprache'
      AND preferences->>'sprache' NOT IN ('deutsch', 'englisch')
    ORDER BY user_id;
"

# --- Perform the migration in a single transaction ----------------------
echo "Applying migration..."
migrated=$(psql_run -t -A <<'SQL'
BEGIN;

UPDATE alice.user_profiles
SET preferences = jsonb_set(preferences, '{sprache}', '"de"'),
    last_updated = NOW()
WHERE preferences->>'sprache' = 'deutsch';

UPDATE alice.user_profiles
SET preferences = jsonb_set(preferences, '{sprache}', '"en"'),
    last_updated = NOW()
WHERE preferences->>'sprache' = 'englisch';

-- Count of rows now holding the migrated codes (for reporting only).
SELECT count(*)
FROM alice.user_profiles
WHERE preferences->>'sprache' IN ('de', 'en');

COMMIT;
SQL
)

echo ""
echo "------------------------------------------------------------"
echo -e "  Profiles now on ISO codes (de/en): ${GREEN}${migrated}${NC}"
echo "------------------------------------------------------------"
echo -e "${GREEN}Migration complete.${NC}"
