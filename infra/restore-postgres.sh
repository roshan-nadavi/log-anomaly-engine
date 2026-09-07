#!/bin/bash
# Restore a Postgres backup created by backup-postgres.sh.
#
# Usage: ./restore-postgres.sh <timestamp>.sql.gz
#   e.g. ./restore-postgres.sh 20260907T031500Z.sql.gz
#
# Downloads the named backup from GCS, drops and recreates the
# database, and replays the dump into it. Destructive — confirms
# before overwriting.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <backup-filename>.sql.gz" >&2
  echo "list available backups: gcloud storage ls gs://log-anomaly-engine-pg-backups/" >&2
  exit 1
fi

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUCKET="gs://log-anomaly-engine-pg-backups"
SA_KEY="/etc/gcp/postgres-backup-sa.json"
BACKUP_FILE="$1"
LOCAL_PATH="/tmp/${BACKUP_FILE}"

cd "$COMPOSE_DIR"

read -p "This will DROP and recreate the database, replacing all current data. Continue? [y/N] " confirm
if [ "$confirm" != "y" ]; then
  echo "aborted"
  exit 1
fi

sudo gcloud auth activate-service-account --key-file="$SA_KEY" --quiet
sudo gcloud storage cp "${BUCKET}/${BACKUP_FILE}" "$LOCAL_PATH"

docker compose exec -T postgres sh -c '
  psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";" &&
  psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE \"$POSTGRES_DB\";"
'
gunzip -c "$LOCAL_PATH" | docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

rm -f "$LOCAL_PATH"
echo "restore complete: ${BACKUP_FILE}"
