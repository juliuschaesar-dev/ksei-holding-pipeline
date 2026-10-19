#!/usr/bin/env bash
# Idempotent bootstrap, then serve. Nothing is configured by hand: the dashboard, its datasets and
# the ClickHouse connection come from superset/assets/ (see superset/export_assets.py).
set -euo pipefail
superset db upgrade
superset fab create-admin \
  --username "$SUPERSET_ADMIN_USER" --password "$SUPERSET_ADMIN_PASSWORD" \
  --firstname Admin --lastname User --email admin@example.com || true
superset init

# An export masks the connection password, so the real URI (from env) is written into a scratch
# copy of the assets before importing. The password never lands in the repository or the image.
# With no exported dashboard yet (a brand-new project) there is simply nothing to import.
if [ -f /app/assets/metadata.yaml ]; then
  rm -rf /tmp/assets && cp -r /app/assets /tmp/assets
  /app/.venv/bin/python /app/provision_connection.py /tmp/assets/databases
  superset import-directory --overwrite /tmp/assets
  rm -rf /tmp/assets
else
  echo "superset/assets has no exported dashboard; skipping import"
fi

exec /app/docker/entrypoints/run-server.sh
