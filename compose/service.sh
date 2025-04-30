#!/usr/bin/env bash
#
# alice-service-manage.sh
#
# Syntax:
#   ./alice-service-manage.sh <start|stop|restart|status|logs> [service …]
#   ./alice-service-manage.sh list
#

# Standard-Reihenfolge, falls keine Services angegeben werden
DEFAULT_SERVICES=(whisper piper ollama mqtt alice-llm-router)

print_usage() {
  cat <<EOF
Verwendung:
  $0 <start|stop|restart|status|logs> [service …]
  $0 list                      # zeigt verfügbare Services
EOF
  exit 1
}

ACTION="$1"
shift || true   # übrige Argumente sind die gewünsch­ten Services

# Sonderfall: Liste anzeigen
[[ "$ACTION" == "list" ]] && { printf '%s\n' "${DEFAULT_SERVICES[@]}"; exit 0; }

# Wenn keine Services spezifiziert → alle Standard-Services
SERVICES=("$@")
[[ ${#SERVICES[@]} -eq 0 ]] && SERVICES=("${DEFAULT_SERVICES[@]}")

# Verzeichnis, in dem dieses Skript liegt (→ compose-Wurzel)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for SERVICE in "${SERVICES[@]}"; do
  SERVICE_DIR="${SCRIPT_DIR}/${SERVICE}"

  # Verfügbar?
  [[ ! -f "${SERVICE_DIR}/docker-compose.yml" ]] && {
    echo "⚠️  Service '$SERVICE' nicht gefunden – überspringe."
    continue
  }

  echo "===> ${ACTION^^} $SERVICE"
  pushd "$SERVICE_DIR" >/dev/null || continue
  case "$ACTION" in
    start)   docker compose up -d ;;
    stop)    docker compose down ;;
    restart) docker compose down && docker compose up -d ;;
    status)  docker compose ps ;;
    logs)    docker compose logs --tail=20 ;;
    *)       print_usage ;;
  esac
  popd >/dev/null
done
