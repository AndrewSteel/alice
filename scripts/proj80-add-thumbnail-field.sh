#!/bin/bash
# ============================================================
# PROJ-80: Declare thumbnail_path on the 6 DMS-type collections
# ============================================================
# alice-dms-thumbnailer already PATCHes thumbnail_path (snake_case)
# onto every successfully inserted document regardless of type —
# Weaviate accepted this without a schema declaration. This script
# only adds the missing property declaration so the field shows up
# in schema introspection and the PROJ-80 coverage query can rely
# on it. No backfill needed — the data is already there.
#
# Collections: Invoice, BankStatement, Document, Email,
#              SecuritySettlement, Contract
#
# Usage:
#   ./proj80-add-thumbnail-field.sh [WEAVIATE_URL]
#   ./proj80-add-thumbnail-field.sh http://172.20.0.4:8080
# ============================================================
set -euo pipefail

WEAVIATE_URL="${1:-http://weaviate:8080}"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

COLLECTIONS=(Invoice BankStatement Document Email SecuritySettlement Contract)

echo "============================================================"
echo "PROJ-80: Weaviate thumbnail_path migration"
echo "============================================================"
echo "Weaviate: ${WEAVIATE_URL}"
echo ""

add_property() {
    local cls="$1"
    local name="$2"
    local body="$3"
    echo -n "  ${cls}.${name}: "

    existing=$(curl -s "${WEAVIATE_URL}/v1/schema/${cls}" | jq -r '.properties[]?.name // empty' 2>/dev/null | grep -x "${name}" || true)
    if [ -n "$existing" ]; then
        echo -e "${YELLOW}already exists — skipped${NC}"
        return 0
    fi

    http_code=$(curl -s -o /tmp/wv_resp.json -w "%{http_code}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d "$body" \
        "${WEAVIATE_URL}/v1/schema/${cls}/properties")

    if [[ "$http_code" == 2* ]]; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}ERROR (HTTP ${http_code})${NC}"
        cat /tmp/wv_resp.json 2>/dev/null && echo ""
        return 1
    fi
}

success=0
errors=0
for cls in "${COLLECTIONS[@]}"; do
    if add_property "$cls" "thumbnail_path" '{"name":"thumbnail_path","dataType":["text"],"description":"Path to generated thumbnail (set by alice-dms-thumbnailer after done event)"}'; then
        success=$((success+1))
    else
        errors=$((errors+1))
    fi
done

echo ""
echo "------------------------------------------------------------"
echo -e "  Success: ${GREEN}${success}${NC}  Errors: ${RED}${errors}${NC}"
echo "------------------------------------------------------------"

[ "$errors" -eq 0 ] && echo -e "${GREEN}Migration complete.${NC}" && exit 0
echo -e "${RED}Migration finished with errors.${NC}" && exit 1
