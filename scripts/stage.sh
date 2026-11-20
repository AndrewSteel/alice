#!/usr/bin/env bash
# Staging on the server: runs a service from a branch or PR NEXT TO the production
# container, with the real .env, keys and networks, but without nginx route and
# without the production DNS name. Use it after the Software Factory's PR is
# green and before you deploy.
#
#   scripts/stage.sh <service> <ref>      e.g. alice-lists origin/factory/123, or a PR number: alice-lists 123
#   scripts/stage.sh <service> --logs     follow the staging container's logs
#   scripts/stage.sh <service> --down     remove the staging container, image and files
#
#   STAGE_HOST=ki.lan          server (ssh, docker group); "local" when running on the server itself
#   COMPOSE_ROOT=/srv/compose  where the production compose stacks and .env files live
#   STAGE_DIR='~/alice-staging'  working directory on the server
#   -y                         skip the confirmation
#
# The staging container is called <service>-staging and reachable only from the
# production networks under that name, e.g.
#   ssh ki.lan docker run --rm --network backend curlimages/curl -s http://alice-lists-staging:8010/health
#
# It works on PRODUCTION DATA (same Postgres, Redis, Weaviate, MQTT, Home Assistant).
# Background work (MQTT listeners, polling, schedules) runs twice while it is up.
#
# Always uses THIS copy of stage.sh and scripts/lib/, never the one from <ref>.
# Only the service directory (Dockerfile, code, compose.yml) comes from <ref>.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
HOST="${STAGE_HOST:-ki.lan}"
COMPOSE_ROOT="${COMPOSE_ROOT:-/srv/compose}"
STAGE_DIR="${STAGE_DIR:-~/alice-staging}"
YES=""
ARGS=()
for a in "$@"; do [ "$a" = "-y" ] && YES=1 || ARGS+=("$a"); done
set -- "${ARGS[@]}"
[ $# -eq 2 ] || { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
SVC="$1" REF="$2"
[[ "$SVC" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "Invalid service name: $SVC" >&2; exit 2; }
REL="automations/$SVC"
PROJECT="$SVC-staging"
RDIR="$STAGE_DIR/$SVC"

on_server() { if [ "$HOST" = local ]; then bash -c "$1"; else ssh "$HOST" "$1"; fi; }
compose() { on_server "cd $RDIR && docker compose -p $PROJECT -f compose.staging.json $1"; }

case "$REF" in
  --logs) compose "logs -f --tail 200"; exit ;;
  --down)
    compose "down --rmi all --remove-orphans" || true
    on_server "rm -rf $RDIR"
    echo "✓ $PROJECT removed. Production $SVC is unchanged."
    exit ;;
esac

# ---- resolve the ref ----
git fetch -q origin
if [[ "$REF" =~ ^[0-9]+$ ]]; then
  git fetch -q origin "pull/$REF/head" && SHA=$(git rev-parse FETCH_HEAD)
  echo "PR #$REF → ${SHA:0:12}"
else
  SHA=$(git rev-parse --verify "$REF^{commit}") || { echo "Unknown ref: $REF" >&2; exit 2; }
fi
SRC="docker/compose/$REL"
git cat-file -e "$SHA:$SRC/compose.yml" 2>/dev/null || { echo "$SRC/compose.yml does not exist in $REF" >&2; exit 2; }
BASE=$(git merge-base origin/dev "$SHA")

# ---- show what will run with the real secrets ----
echo "Changes in $SRC (origin/dev → $REF):"
git --no-pager diff --stat "$BASE" "$SHA" -- "$SRC" | sed 's/^/  /'
if ! git diff --quiet "$BASE" "$SHA" -- "$SRC/compose.yml"; then
  echo
  echo "compose.yml changed. It runs on the server with the real .env, check volumes, ports and privileges:"
  git --no-pager diff --color=auto "$BASE" "$SHA" -- "$SRC/compose.yml"
fi
if ! git diff --quiet "$BASE" "$SHA" -- scripts/stage.sh scripts/lib/; then
  echo
  echo "Note: $REF also changes scripts/stage.sh or scripts/lib/. That version is NOT used here."
fi
if [ -z "$YES" ]; then
  echo
  read -r -p "Start $PROJECT on $HOST with the production .env of $SVC? [y/N] " ok </dev/tty
  [[ "$ok" =~ ^[yYjJ] ]] || { echo "Aborted."; exit 1; }
fi

# ---- export the service directory and generate the staging compose file ----
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/compose"
git archive "$SHA" "$SRC" | tar -x -C "$WORK/compose" --strip-components=2  # → $WORK/compose/automations/<svc>
SDIR="$WORK/compose/$REL"
IMAGE="alice-staging/$SVC:${SHA:0:12}"
uv run --no-project -q --with "pyyaml>=6,<7" python -I "$ROOT/scripts/lib/compose_service.py" \
  stage "$SDIR" "$IMAGE" "$COMPOSE_ROOT" "$SDIR/compose.staging.json" >"$WORK/info"
{ read -r _; read -r NETS; } <"$WORK/info"

# ---- copy to the server, build and start ----
echo "▶ Copy to $HOST:$RDIR"
on_server "rm -rf $RDIR && mkdir -p $RDIR"
if [ "$HOST" = local ]; then tar -C "$SDIR" -c . | bash -c "tar -x -C $RDIR"
else tar -C "$SDIR" -cz . | ssh "$HOST" "tar -xz -C $RDIR"
fi
# The production .env also feeds ${VAR} interpolation, as it does for the production stack.
ENVFILE="$COMPOSE_ROOT/$REL/.env"
on_server "test -r $ENVFILE" || { echo "$HOST: $ENVFILE is missing or not readable." >&2; exit 1; }
echo "▶ Build $IMAGE and start $PROJECT (waits for the healthcheck)"
compose "--env-file $ENVFILE build --quiet" || { echo "✗ Build failed." >&2; exit 1; }
if ! compose "--env-file $ENVFILE up -d --wait --wait-timeout 300"; then
  echo "✗ $PROJECT did not become healthy. Logs:"
  compose "logs --tail 80" || true
  echo "Remove with: scripts/stage.sh $SVC --down"
  exit 1
fi

echo
echo "✓ $PROJECT is running on $HOST (${SHA:0:12}), next to production $SVC."
echo "  Reachable as $PROJECT on: $NETS (no nginx route)"
echo "  Logs:    scripts/stage.sh $SVC --logs"
echo "  Remove:  scripts/stage.sh $SVC --down"
echo "  ! Uses production data. Background work (MQTT, polling, schedules) runs twice while it is up."
echo "  Good? Merge the PR and deploy as usual; then remove the staging container."
