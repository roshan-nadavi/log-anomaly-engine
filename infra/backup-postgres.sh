#!/bin/bash
# Nightly Postgres backup: pg_dump inside the running container -> gzip
# -> upload to GCS. Runs as root via cron on the deploy VM (needs both
# Docker access and read access to the backup service account's key).
#
# The backup service account (postgres-backup@...) only has
# roles/storage.objectAdmin on this one bucket — not project-wide
# access — so a leaked key can't do anything beyond read/write backups.
# The bucket has a 30-day age-based lifecycle rule, so storage cost
# stays near zero indefinitely without manual cleanup.
#
# Install: sudo crontab -e
#   0 3 * * * /home/roshan/log-anomaly-engine/infra/backup-postgres.sh >> /var/log/postgres-backup.log 2>&1
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUCKET="gs://log-anomaly-engine-pg-backups"
SA_KEY="/etc/gcp/postgres-backup-sa.json"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="/tmp/logpulse-backup-${TIMESTAMP}.sql.gz"

cd "$COMPOSE_DIR"

echo "[$(date -u -Iseconds)] starting backup"

docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$DUMP_FILE"

gcloud auth activate-service-account --key-file="$SA_KEY" --quiet
gcloud storage cp "$DUMP_FILE" "${BUCKET}/${TIMESTAMP}.sql.gz"

rm -f "$DUMP_FILE"

echo "[$(date -u -Iseconds)] backup uploaded: ${TIMESTAMP}.sql.gz"
