#!/bin/bash
# ============================================================
# Alice - Weaviate Schema Setup
# ============================================================
# Creates all collections for Alice in Weaviate
#
# Prerequisites:
#   - Weaviate is running and reachable
#   - curl and jq are installed
#
# Usage:
#   ./init-weaviate-schema.sh [WEAVIATE_URL]
#
# Example:
#   ./init-weaviate-schema.sh http://localhost:8080
#   ./init-weaviate-schema.sh http://weaviate:8080
# ============================================================

# Note: intentionally no 'set -e' - error counting in the main loop requires
# create_collection() to be able to return non-zero without aborting the script.

# Configuration
WEAVIATE_URL="${1:-http://weaviate:8080}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_DIR="${SCRIPT_DIR}/../schemas"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "============================================================"
echo "Alice - Weaviate Schema Setup"
echo "============================================================"
echo ""
echo "Weaviate URL: ${WEAVIATE_URL}"
echo "Schema Dir:   ${SCHEMA_DIR}"
echo ""

# Check if Weaviate is reachable
echo -n "Checking Weaviate connection... "
if ! curl -s "${WEAVIATE_URL}/v1/.well-known/ready" > /dev/null 2>&1; then
    echo -e "${RED}ERROR${NC}"
    echo "   Weaviate is not reachable at ${WEAVIATE_URL}"
    echo "   Please check if Weaviate is running."
    exit 1
fi
echo -e "${GREEN}OK${NC}"

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo -e "${RED}ERROR: jq is not installed${NC}"
    echo "   Install: apt-get install jq"
    exit 1
fi

# Function: Create collection
create_collection() {
    local schema_file="$1"
    local class_name=$(jq -r '.class' "$schema_file")

    echo -n "Creating collection '${class_name}'... "

    # Check if collection already exists
    local exists
    exists=$(curl -s "${WEAVIATE_URL}/v1/schema/${class_name}" 2>/dev/null | jq -r '.class // empty' 2>/dev/null || true)

    if [ -n "$exists" ]; then
        echo -e "${YELLOW}already exists${NC}"
        return 0
    fi

    # Create collection
    local response=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -d @"$schema_file" \
        "${WEAVIATE_URL}/v1/schema")

    # Check for errors
    local error
    error=$(echo "$response" | jq -r '.error // empty' 2>/dev/null || true)
    if [ -n "$error" ]; then
        echo -e "${RED}ERROR${NC}"
        echo "   $error"
        return 1
    fi

    echo -e "${GREEN}OK${NC}"
    return 0
}

# Function: Delete collection (for reset)
delete_collection() {
    local class_name="$1"

    echo -n "Deleting collection '${class_name}'... "

    local response=$(curl -s -X DELETE "${WEAVIATE_URL}/v1/schema/${class_name}")

    echo -e "${GREEN}OK${NC}"
}

# Main logic
echo ""
echo "Creating collections..."
echo "------------------------------------------------------------"

# List of schema files
SCHEMAS=(
    "alice-memory.json"
    "invoice.json"
    "bank-statement.json"
    "security-settlement.json"
    "document.json"
    "email.json"
    "contract.json"
    "ha-intent.json"
)

# Optional: Reset flag
if [ "$2" == "--reset" ]; then
    echo ""
    echo -e "${YELLOW}WARNING: RESET MODE — Deleting existing collections...${NC}"
    echo ""

    for schema in "${SCHEMAS[@]}"; do
        class_name=$(jq -r '.class' "${SCHEMA_DIR}/${schema}" 2>/dev/null || echo "")
        if [ -n "$class_name" ]; then
            delete_collection "$class_name"
        fi
    done
    echo ""
fi

# Create collections
success_count=0
error_count=0

for schema in "${SCHEMAS[@]}"; do
    schema_path="${SCHEMA_DIR}/${schema}"

    if [ -f "$schema_path" ]; then
        # Call function and store exit code
        create_collection "$schema_path"
        result=$?

        # Evaluate exit code
        if [ $result -eq 0 ]; then
            success_count=$((success_count + 1))
        else
            error_count=$((error_count + 1))
        fi
    else
        echo -e "${YELLOW}WARNING: Schema file not found: ${schema}${NC}"
        error_count=$((error_count + 1))
    fi
done

echo ""
echo "------------------------------------------------------------"
echo "Summary"
echo "------------------------------------------------------------"
echo -e "   Successful: ${GREEN}${success_count}${NC}"
echo -e "   Errors:     ${RED}${error_count}${NC}"
echo ""

# Show current schema
echo "Current collections in Weaviate:"
echo "------------------------------------------------------------"
curl -s "${WEAVIATE_URL}/v1/schema" | jq -r '.classes[].class' | while read class; do
    echo "   - $class"
done
echo ""

if [ $error_count -eq 0 ]; then
    echo -e "${GREEN}Schema setup completed successfully!${NC}"
    exit 0
else
    echo -e "${YELLOW}Schema setup completed with warnings${NC}"
    exit 1
fi
