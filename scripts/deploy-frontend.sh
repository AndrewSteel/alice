#!/bin/bash
# Deploy Alice React frontend to nginx html root
# Usage: ./scripts/deploy-frontend.sh
# No nginx restart required - nginx serves files from the volume directly.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="$REPO_ROOT/frontend"
NGINX_HTML="$REPO_ROOT/docker/compose/infra/nginx/html"

echo "==> Building frontend..."
cd "$FRONTEND_DIR"
npm run build

echo "==> Deploying to nginx html root..."
# Copy all build output to the nginx html root.
# finance_upload/ is excluded because it is managed separately.
rsync -a --delete \
  --exclude='finance_upload' \
  "$FRONTEND_DIR/out/" "$NGINX_HTML/"

echo "==> Done. Sync to server with: ./sync-compose.sh"
