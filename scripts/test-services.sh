#!/usr/bin/env bash
# Runs the pytest suites of the Alice services (docker/compose/automations/*/tests).
#
# DB-backed integration tests (LISTS_TEST_DSN, CALENDAR_TEST_DSN) run against a
# throwaway PostgreSQL from docker/test/compose.test.yml with sql/init-schema.sql
# applied. The stack is started here and removed afterwards.
#
#   scripts/test-services.sh                    all services
#   scripts/test-services.sh alice-lists ...    only these services
#   NO_DB=1 scripts/test-services.sh            unit tests only, no containers
#   SKIP="svc1 svc2" scripts/test-services.sh   all services except these
#
# Each service gets its own Python 3.12 virtualenv outside the repo
# (~/.cache/alice-test-venvs/<service>), your own <service>/.venv stays untouched.
# A service can provide tests/install-test-deps.sh for special dependencies
# (e.g. CPU-only torch); it runs with VIRTUAL_ENV set.
#
# Inside the Software Factory (FACTORY_DOCKER=1) the job reaches the test
# containers by name; locally they are published on 127.0.0.1.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

SERVICES=("$@")
if [ ${#SERVICES[@]} -eq 0 ]; then
  for d in docker/compose/automations/*/tests; do
    svc=$(basename "$(dirname "$d")")
    [[ " ${SKIP:-} " == *" $svc "* ]] && { echo "• skipped: $svc"; continue; }
    SERVICES+=("$svc")
  done
fi
command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 2; }
VENVS="${XDG_CACHE_HOME:-$HOME/.cache}/alice-test-venvs"
# Some tests (alice-calendar) build expected times in the machine's local zone.
# Pin it so results are identical on a dev machine and in UTC containers.
export TZ=Europe/Berlin

# ---- throwaway test databases ----
PROJECT=sf-alice-test
if [ -z "${NO_DB:-}" ]; then
  if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
    echo "Docker not reachable: set NO_DB=1 to run unit tests only." >&2
    exit 2
  fi
  if [ -n "${FACTORY_DOCKER:-}" ]; then
    FILES=(-f docker/test/compose.test.yml); PG_HOST=test-postgres; PG_PORT=5432; REDIS=redis://test-redis:6379/0
  else
    FILES=(-f docker/test/compose.test.yml -f docker/test/compose.ports.yml); PG_HOST=127.0.0.1; PG_PORT=55432; REDIS=redis://127.0.0.1:56379/0
  fi
  cleanup() { docker compose -p "$PROJECT" "${FILES[@]}" down -v --remove-orphans >/dev/null 2>&1; }
  trap cleanup EXIT
  echo "▶ Starting test databases ($PROJECT)"
  docker compose -p "$PROJECT" "${FILES[@]}" up -d --wait --quiet-pull || { echo "Test databases did not start." >&2; exit 1; }
  DSN="postgresql://alice:test@${PG_HOST}:${PG_PORT}/alice"
  # TEST_POSTGRES_DSN for new tests; LISTS_/CALENDAR_TEST_DSN for the existing ones
  export TEST_POSTGRES_DSN="$DSN" LISTS_TEST_DSN="$DSN" CALENDAR_TEST_DSN="$DSN" TEST_REDIS_URL="$REDIS"
fi

FAILED=()
for svc in "${SERVICES[@]}"; do
  dir="docker/compose/automations/$svc"
  [ -d "$dir/tests" ] || { echo "✗ $svc: no tests/ directory"; FAILED+=("$svc"); continue; }
  echo "▶ $svc"
  (
    set -e
    cd "$dir"
    export VIRTUAL_ENV="$VENVS/$svc"
    "$VIRTUAL_ENV/bin/python" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>/dev/null \
      || uv venv -q --clear --python 3.12 "$VIRTUAL_ENV"
    CONSTRAINTS=()
    [ -f constraints.txt ] && CONSTRAINTS=(-c constraints.txt)
    if [ -x tests/install-test-deps.sh ]; then
      tests/install-test-deps.sh
    elif [ -f requirements-dev.txt ]; then
      uv pip install -q -r requirements-dev.txt "${CONSTRAINTS[@]}"
    else
      uv pip install -q -r requirements.txt "${CONSTRAINTS[@]}" "pytest>=8.0,<9.0" "pytest-asyncio>=0.23,<0.25"
    fi
    if [ -f pytest.ini ]; then "$VIRTUAL_ENV/bin/python" -m pytest -q
    else "$VIRTUAL_ENV/bin/python" -m pytest -q -o asyncio_mode=auto -o pythonpath=. tests
    fi
  ) || FAILED+=("$svc")
done

echo
if [ ${#FAILED[@]} -gt 0 ]; then echo "✗ Failed: ${FAILED[*]}"; exit 1; fi
echo "✓ All service tests passed (${SERVICES[*]})"
