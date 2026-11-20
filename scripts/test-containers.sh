#!/usr/bin/env bash
# Container test for changed services: builds each service from its Dockerfile
# (as defined in its compose.yml), starts it with throwaway Postgres and Redis
# (plus Weaviate / MQTT if the service uses them) and waits until its
# healthcheck reports healthy. Then runs tests/container-smoke.sh if present.
#
#   scripts/test-containers.sh                 services changed since origin/main
#   scripts/test-containers.sh alice-lists ... only these services
#   SKIP="svc1 svc2" scripts/test-containers.sh
#   CT_BASE=origin/dev scripts/test-containers.sh
#
# The test container gets no production paths, networks, ports, GPUs or .env:
#   - environment: the service's .env.example, with database, Redis, Weaviate and
#     MQTT settings pointed at the test containers, then tests/container.env
#     (committed, test values only) on top
#   - /run/secrets: a fresh RSA key pair as jwt_private.pem / jwt_public.pem;
#     other secret files from tests/container-secrets/<name>, else the text "test"
#   - tests/container-smoke.sh gets CT_CONTAINER, CT_SERVICE and CT_PROJECT,
#     typically: docker exec "$CT_CONTAINER" python -c '...urlopen(...)...'
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
AUTOMATIONS=docker/compose/automations
TIMEOUT="${CT_TIMEOUT:-240}"

SERVICES=("$@")
if [ ${#SERVICES[@]} -eq 0 ]; then
  BASE="${CT_BASE:-origin/${FACTORY_DEFAULT_BRANCH:-main}}"
  MB=$(git merge-base "$BASE" HEAD 2>/dev/null) || { echo "Base $BASE not found (git fetch?)" >&2; exit 2; }
  while read -r svc; do
    [ -n "$svc" ] || continue
    [[ " ${SKIP:-} " == *" $svc "* ]] && { echo "• skipped (SKIP): $svc"; continue; }
    d="$AUTOMATIONS/$svc"
    if [ ! -f "$d/compose.yml" ] || ! grep -qE '^[[:space:]]+build:' "$d/compose.yml"; then
      echo "• not a built service, nothing to test: $svc"; continue
    fi
    SERVICES+=("$svc")
  done < <({ git diff --name-only "$MB" -- "$AUTOMATIONS"; git ls-files --others --exclude-standard -- "$AUTOMATIONS"; } \
           | cut -d/ -f4 | sort -u)
  if [ ${#SERVICES[@]} -eq 0 ]; then echo "✓ No changed service with a Dockerfile, no container test needed."; exit 0; fi
fi
for tool in docker uv openssl; do
  command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 2; }
done
docker info >/dev/null 2>&1 || { echo "Docker not reachable." >&2; exit 2; }
PY=(uv run --no-project -q --with "pyyaml>=6,<7" python -I "$ROOT/scripts/lib/compose_service.py")
RUN="$(date +%s)-$$"

FAILED=()
test_service() {
  # No "local": test_service runs in a subshell, and the EXIT trap below still needs these.
  svc="$1"; dir="$AUTOMATIONS/$1"
  work=$(mktemp -d)
  tag="alice-ct/$svc:$RUN"
  project="alice-ct-$svc"
  info=$("${PY[@]}" test "$dir" "$tag" "$work") || { rm -rf "$work"; return 1; }
  { read -r name; read -r profiles; read -r secrets; } <<<"$info"
  files=(-f docker/test/compose.test.yml -f "$work/compose.json"); prof=()
  for p in $profiles; do prof+=(--profile "$p"); done
  dc() { docker compose -p "$project" "${files[@]}" "${prof[@]}" "$@"; }
  # shellcheck disable=SC2317
  cleanup() {
    dc down -v --remove-orphans >/dev/null 2>&1
    docker image rm "$tag" >/dev/null 2>&1
    rm -rf "$work"
  }
  trap cleanup EXIT # test_service runs in a subshell
  fail() { echo "  ✗ $*"; echo "  --- last log lines of $name ---"; dc logs --no-color --tail 80 "$name" 2>&1 | sed 's/^/  | /'; return 1; }

  echo "  build image ($dir/Dockerfile)"
  # one retry: a flaky package mirror should not fail the check
  dc build -q "$name" >"$work/build.log" 2>&1 || dc build -q "$name" >"$work/build.log" 2>&1 \
    || { echo "  ✗ build failed"; tail -40 "$work/build.log" | sed 's/^/  | /'; return 1; }

  echo "  start test databases${profiles:+ (+ $profiles)}"
  mapfile -t deps < <(dc config --services | grep -vx "$name")
  dc up -d --wait --quiet-pull "${deps[@]}" >/dev/null 2>&1 || { echo "  ✗ test databases did not start"; return 1; }

  dc up --no-start "$name" >/dev/null 2>&1 || { echo "  ✗ container could not be created"; dc up --no-start "$name" 2>&1 | tail -10; return 1; }
  cid=$(dc ps -a -q "$name")
  if [ -n "$secrets" ]; then
    mkdir -p "$work/secrets"
    openssl genrsa -out "$work/secrets/jwt_private.pem" 2048 2>/dev/null
    openssl rsa -in "$work/secrets/jwt_private.pem" -pubout -out "$work/secrets/jwt_public.pem" 2>/dev/null
    for s in $secrets; do
      if [ -e "$dir/tests/container-secrets/$s" ]; then cp -r "$dir/tests/container-secrets/$s" "$work/secrets/$s"
      elif [ ! -e "$work/secrets/$s" ]; then echo test >"$work/secrets/$s"
      fi
    done
    chmod -R a+rX "$work/secrets"
    docker cp -q "$work/secrets/." "$cid:/run/secrets/" || { echo "  ✗ could not copy test secrets"; return 1; }
  fi

  echo "  start $name, wait for healthcheck (max ${TIMEOUT}s)"
  dc up -d --wait --wait-timeout "$TIMEOUT" "$name" >/dev/null 2>&1 || fail "did not become healthy" || return 1
  sleep 5 # catches services that crash right after the first successful check
  [ "$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null)" = true ] || fail "stopped after start" || return 1
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")
  case "$health" in
    healthy) echo "  ✓ healthy" ;;
    none) echo "  ! no healthcheck in compose.yml, only checked that it keeps running" ;;
    *) fail "health status: $health" || return 1 ;;
  esac

  if [ -x "$dir/tests/container-smoke.sh" ]; then
    echo "  run tests/container-smoke.sh"
    CT_CONTAINER="$cid" CT_SERVICE="$name" CT_PROJECT="$project" "$dir/tests/container-smoke.sh" 2>&1 | sed 's/^/  | /'
    [ "${PIPESTATUS[0]}" -eq 0 ] || fail "smoke test failed" || return 1
    echo "  ✓ smoke test"
  fi
}

for svc in "${SERVICES[@]}"; do
  echo "▶ $svc"
  [ -d "$AUTOMATIONS/$svc" ] || { echo "  ✗ $AUTOMATIONS/$svc not found"; FAILED+=("$svc"); continue; }
  ( test_service "$svc" ) || FAILED+=("$svc")
done

echo
if [ ${#FAILED[@]} -gt 0 ]; then echo "✗ Container test failed: ${FAILED[*]}"; exit 1; fi
echo "✓ Container test passed (${SERVICES[*]})"
