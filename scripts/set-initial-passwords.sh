#!/usr/bin/env bash
# ============================================================
# set-initial-passwords.sh
#
# Interactive script to set bcrypt password hashes for Alice users.
# Hashes passwords locally using Python bcrypt (no network dependency on alice-auth).
#
# Prerequisites:
#   - python3 + bcrypt installed (pip3 install bcrypt)
#   - PostgreSQL container is running
#   - docker exec access to the postgres container
#
# Usage:
#   ./scripts/set-initial-passwords.sh
# ============================================================

set -euo pipefail

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres}"
DB_USER="${DB_USER:-user}"
DB_NAME="${DB_NAME:-alice}"

echo "============================================================"
echo "  Alice — Initial Password Setup"
echo "============================================================"
echo ""
echo "Postgres:     ${POSTGRES_CONTAINER} (db: ${DB_NAME}, user: ${DB_USER})"
echo ""

# Check that python3 + bcrypt are available
if ! python3 -c "import bcrypt" 2>/dev/null; then
    echo "ERROR: python3 + bcrypt required. Install with: pip3 install bcrypt"
    exit 1
fi

# Get list of users from DB
echo "Users in alice.users:"
docker exec "${POSTGRES_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" \
    -c "SELECT username, role, is_active, CASE WHEN password_hash IS NOT NULL THEN 'set' ELSE 'NOT SET' END AS password FROM alice.users ORDER BY username;" \
    2>/dev/null || {
    echo "ERROR: Could not query alice.users. Is PostgreSQL running?"
    exit 1
}

echo ""
echo "Enter passwords for each user. Press Enter to skip a user."
echo ""

# Read all usernames
mapfile -t USERNAMES < <(docker exec "${POSTGRES_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" \
    -t -c "SELECT username FROM alice.users ORDER BY username;" 2>/dev/null | tr -d ' ')

for username in "${USERNAMES[@]}"; do
    [[ -z "$username" ]] && continue

    read -rsp "Password for '${username}' (Enter to skip): " password
    echo ""

    if [[ -z "$password" ]]; then
        echo "  Skipping ${username}"
        continue
    fi

    # Hash password locally using Python bcrypt (no network dependency)
    hash=$(printf '%s' "$password" | python3 -c '
import sys, bcrypt
pw = sys.stdin.buffer.read()
hashed = bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12))
print(hashed.decode("utf-8"))
' 2>/dev/null) || {
        echo "  ERROR: Failed to hash password for ${username}. Is python3 + bcrypt installed?"
        echo "  Install: pip3 install bcrypt"
        continue
    }

    # Validate bcrypt hash format: $2b$12$<53 chars of [./A-Za-z0-9]>
    if ! [[ "$hash" =~ ^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$ ]]; then
        echo "  ERROR: Invalid bcrypt hash format for ${username} — aborting"
        continue
    fi

    # Update hash in DB — hash format validated above (no SQL injection risk)
    docker exec "${POSTGRES_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -q \
        -c "UPDATE alice.users SET password_hash = '${hash}' WHERE username = '${username}';" \
        > /dev/null 2>&1 && \
        echo "  OK: password set for ${username}" || \
        echo "  ERROR: DB update failed for ${username}"
done

echo ""
echo "Done. Verify with:"
echo "  docker exec ${POSTGRES_CONTAINER} psql -U ${DB_USER} -d ${DB_NAME} \\"
echo "    -c \"SELECT username, role, is_active, CASE WHEN password_hash IS NOT NULL THEN 'set' ELSE 'NOT SET' END AS password FROM alice.users;\""
