#!/bin/bash
# ============================================================
# Alice - Weaviate Schema Setup
# ============================================================
# Erstellt alle Collections für Alice in Weaviate
#
# Voraussetzungen:
#   - Weaviate läuft und ist erreichbar
#   - curl und jq sind installiert
#
# Verwendung:
#   ./init-weaviate-schema.sh [WEAVIATE_URL]
#
# Beispiel:
#   ./init-weaviate-schema.sh http://localhost:8080
#   ./init-weaviate-schema.sh http://weaviate:8080
# ============================================================

# Note: intentionally no 'set -e' - error counting in the main loop requires
# create_collection() to be able to return non-zero without aborting the script.

# Konfiguration
WEAVIATE_URL="${1:-http://weaviate:8080}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_DIR="${SCRIPT_DIR}/../schemas"

# Farben für Output
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

# Prüfe ob Weaviate erreichbar ist
echo -n "🔍 Prüfe Weaviate-Verbindung... "
if ! curl -s "${WEAVIATE_URL}/v1/.well-known/ready" > /dev/null 2>&1; then
    echo -e "${RED}FEHLER${NC}"
    echo "   Weaviate ist nicht erreichbar unter ${WEAVIATE_URL}"
    echo "   Bitte prüfe ob Weaviate läuft."
    exit 1
fi
echo -e "${GREEN}OK${NC}"

# Prüfe ob jq installiert ist
if ! command -v jq &> /dev/null; then
    echo -e "${RED}FEHLER: jq ist nicht installiert${NC}"
    echo "   Installation: apt-get install jq"
    exit 1
fi

# Funktion: Collection erstellen
create_collection() {
    local schema_file="$1"
    local class_name=$(jq -r '.class' "$schema_file")

    echo -n "📦 Erstelle Collection '${class_name}'... "

    # Prüfe ob Collection bereits existiert
    local exists
    exists=$(curl -s "${WEAVIATE_URL}/v1/schema/${class_name}" 2>/dev/null | jq -r '.class // empty' 2>/dev/null || true)

    if [ -n "$exists" ]; then
        echo -e "${YELLOW}existiert bereits${NC}"
        return 0
    fi

    # Collection erstellen
    local response=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -d @"$schema_file" \
        "${WEAVIATE_URL}/v1/schema")

    # Prüfe auf Fehler
    local error
    error=$(echo "$response" | jq -r '.error // empty' 2>/dev/null || true)
    if [ -n "$error" ]; then
        echo -e "${RED}FEHLER${NC}"
        echo "   $error"
        return 1
    fi

    echo -e "${GREEN}OK${NC}"
    return 0
}

# Funktion: Collection löschen (für Reset)
delete_collection() {
    local class_name="$1"
    
    echo -n "🗑️  Lösche Collection '${class_name}'... "
    
    local response=$(curl -s -X DELETE "${WEAVIATE_URL}/v1/schema/${class_name}")
    
    echo -e "${GREEN}OK${NC}"
}

# Hauptlogik
echo ""
echo "📚 Erstelle Collections..."
echo "------------------------------------------------------------"

# Liste der Schema-Dateien
SCHEMAS=(
    "alice-memory.json"
    "rechnung.json"
    "kontoauszug.json"
    "wertpapier-abrechnung.json"
    "dokument.json"
    "email.json"
    "vertrag.json"
    "ha-intent.json"
)

# Optional: Reset-Flag
if [ "$2" == "--reset" ]; then
    echo ""
    echo -e "${YELLOW}⚠️  RESET-MODUS: Lösche bestehende Collections...${NC}"
    echo ""
    
    for schema in "${SCHEMAS[@]}"; do
        class_name=$(jq -r '.class' "${SCHEMA_DIR}/${schema}" 2>/dev/null || echo "")
        if [ -n "$class_name" ]; then
            delete_collection "$class_name"
        fi
    done
    echo ""
fi

# Collections erstellen
success_count=0
error_count=0

for schema in "${SCHEMAS[@]}"; do
    schema_path="${SCHEMA_DIR}/${schema}"

    if [ -f "$schema_path" ]; then
        # Rufe Funktion auf und speichere Exit-Code
        create_collection "$schema_path"
        result=$?

        # Werte Exit-Code aus
        if [ $result -eq 0 ]; then
            success_count=$((success_count + 1))
        else
            error_count=$((error_count + 1))
        fi
    else
        echo -e "${YELLOW}⚠️  Schema-Datei nicht gefunden: ${schema}${NC}"
        error_count=$((error_count + 1))
    fi
done

echo ""
echo "------------------------------------------------------------"
echo "📊 Zusammenfassung"
echo "------------------------------------------------------------"
echo -e "   Erfolgreich: ${GREEN}${success_count}${NC}"
echo -e "   Fehler:      ${RED}${error_count}${NC}"
echo ""

# Zeige aktuelles Schema
echo "📋 Aktuelle Collections in Weaviate:"
echo "------------------------------------------------------------"
curl -s "${WEAVIATE_URL}/v1/schema" | jq -r '.classes[].class' | while read class; do
    echo "   • $class"
done
echo ""

if [ $error_count -eq 0 ]; then
    echo -e "${GREEN}✅ Schema-Setup erfolgreich abgeschlossen!${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠️  Schema-Setup mit Warnungen abgeschlossen${NC}"
    exit 1
fi
