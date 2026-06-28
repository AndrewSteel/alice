#!/bin/bash
# ============================================================
# PROJ-55: Add thumbnail_path field to all 7 DMS collections
# ============================================================
# Adds optional String field 'thumbnail_path' to:
#   Invoice, BankStatement, BankTransaction, Document,
#   Email, SecuritySettlement, Contract
#
# Usage:
#   ./proj55-add-thumbnail-path.sh [WEAVIATE_URL]
#   ./proj55-add-thumbnail-path.sh http://172.20.0.4:8080
# ============================================================
set -euo pipefail

WEAVIATE_URL="${1:-http://weaviate:8080}"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

COLLECTIONS=(Invoice BankStatement BankTransaction Document Email SecuritySettlement Contract)

echo "============================================================"
echo "PROJ-55: Weaviate thumbnail_path migration"
echo "============================================================"
echo "Weaviate: ${WEAVIATE_URL}"
echo ""

add_property() {
    local cls="$1"
    echo -n "  ${cls}: "

    # Check if property already exists
    existing=$(curl -s "${WEAVIATE_URL}/v1/schema/${cls}" | jq -r '.properties[]?.name // empty' 2>/dev/null | grep -x "thumbnail_path" || true)
    if [ -n "$existing" ]; then
        echo -e "${YELLOW}already exists — skipped${NC}"
        return 0
    fi

    http_code=$(curl -s -o /tmp/wv_resp.json -w "%{http_code}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d '{"name":"thumbnail_path","dataType":["text"],"description":"Path to generated thumbnail JPEG on warm storage"}' \
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
    if add_property "$cls"; then
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
