#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(pwd)"

LOCAL="$BASE_DIR/docker/compose/"

if [[ ! -d "${LOCAL}" ]]; then
  echo "ERROR: ${LOCAL} existiert nicht."
  exit 1
fi

REMOTE="stan@ki.lan:/srv/compose/"
EXCLUDES="$BASE_DIR/.rsyncignore"

rsync -rtvz --delete --itemize-changes --exclude-from="$EXCLUDES" "$LOCAL" "$REMOTE"
