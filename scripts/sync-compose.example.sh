#!/usr/bin/env bash
# Template: cp scripts/sync-compose.example.sh scripts/sync-compose.sh, then set REMOTE.
set -euo pipefail

BASE_DIR="$(pwd)"

LOCAL="$BASE_DIR/docker/compose/"

if [[ ! -d "${LOCAL}" ]]; then
  echo "ERROR: ${LOCAL} existiert nicht."
  exit 1
fi

REMOTE="user@your-server:/srv/compose/"
EXCLUDES="$BASE_DIR/.rsyncignore"

rsync -rtvz --delete --itemize-changes --exclude-from="$EXCLUDES" "$LOCAL" "$REMOTE"

# Reload nginx if it is running — picks up any conf.d or snippet changes.
# echo "==> Reloading nginx config on the server..."
# ssh user@your-server "docker exec nginx nginx -s reload 2>&1 && echo 'nginx reloaded OK' || echo 'nginx reload skipped (container not running)'"
