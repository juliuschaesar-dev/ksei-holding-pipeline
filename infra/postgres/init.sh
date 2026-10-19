#!/usr/bin/env bash
# Runs once on first start (docker-entrypoint-initdb.d). POSTGRES_DB (Airflow) already exists.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v superset_db="$SUPERSET_DB" <<'SQL'
SELECT format('CREATE DATABASE %I', :'superset_db')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'superset_db')\gexec
SQL
