#!/bin/bash
# alice/scripts/setup-database.sh

POSTGRES_CONTAINER="postgres"
DB_NAME="alice"
DB_USER="alice_user"
DB_PASS="$(openssl rand -base64 16)"  # Zufälliges Passwort

echo "🗄️  Setting up Alice database..."

# Datenbank und User erstellen
docker exec -i $POSTGRES_CONTAINER psql -U postgres << EOF
-- Datenbank erstellen (falls nicht existiert)
SELECT 'CREATE DATABASE $DB_NAME' 
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec

-- User erstellen
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE USER $DB_USER WITH ENCRYPTED PASSWORD '$DB_PASS';
    END IF;
END
\$\$;

-- Rechte vergeben
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
EOF

# Schema erstellen
docker exec -i $POSTGRES_CONTAINER psql -U postgres -d $DB_NAME < sql/init-schema.sql

echo "✅ Database setup complete!"
echo ""
echo "Connection string für n8n:"
echo "postgresql://$DB_USER:$DB_PASS@postgres:5432/$DB_NAME"
echo ""
echo "⚠️  Passwort sicher speichern: $DB_PASS"