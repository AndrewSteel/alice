#!/bin/bash
# ============================================================
# PROJ-78: Add classification confidence fields to 6 DMS collections
# ============================================================
# Adds optional fields to the six classifiable collections:
#   Invoice, BankStatement, Document, Email, SecuritySettlement, Contract
#   - classificationConfidence (number, 0-1)
#   - classificationUncertain  (boolean)
#
# Usage:
#   ./proj78-add-classification-fields.sh [WEAVIATE_URL]
#   ./proj78-add-classification-fields.sh http://172.20.0.4:8080
# ============================================================
set -euo pipefail

WEAVIATE_URL="${1:-http://weaviate:8080}"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

COLLECTIONS=(Invoice BankStatement Document Email SecuritySettlement Contract)

echo "============================================================"
echo "PROJ-78: Weaviate classification-confidence migration"
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
    if add_property "$cls" "classificationConfidence" '{"name":"classificationConfidence","dataType":["number"],"description":"LLM self-reported classification confidence (0-1)"}'; then
        success=$((success+1))
    else
        errors=$((errors+1))
    fi
    if add_property "$cls" "classificationUncertain" '{"name":"classificationUncertain","dataType":["boolean"],"description":"True if the final classification confidence stayed below the threshold after both attempts"}'; then
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
