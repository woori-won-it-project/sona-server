#!/usr/bin/env bash
# Dump file -> Local DB (docker postgres)
# Usage (repo root):
#   ./scripts/db-restore.sh                    # most recently modified dumps/*.dump
#   ./scripts/db-restore.sh dumps/my.dump      # given file
set -euo pipefail
export MSYS_NO_PATHCONV=1  # Git Bash(Windows)에서 /tmp 경로 변환 방지

ROOT="$(cd "$(dirname "$0")/.." && (pwd -W 2>/dev/null || pwd))"  # pwd -W: Git Bash에서 C:/... 형식
ENV_FILE="$ROOT/.env"
COMPOSE_FILE="$ROOT/infra/docker-compose.yml"
if [ $# -ge 1 ] && [ -n "$1" ]; then
  DUMP_FILE="$1"
else
  DUMP_FILE="$(ls -t "$ROOT"/dumps/*.dump 2>/dev/null | head -n1 || true)"
  [ -n "$DUMP_FILE" ] || { echo "No .dump file in $ROOT/dumps" >&2; exit 1; }
fi

[ -f "$ENV_FILE" ] || { echo ".env not found. Copy .env.example to .env first." >&2; exit 1; }
[ -f "$DUMP_FILE" ] || { echo "Dump file not found: $DUMP_FILE" >&2; exit 1; }
env_get() { grep -E "^\s*$1\s*=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '\r' | xargs; }
DB="$(env_get POSTGRES_DB)"; DB="${DB:-sona}"
USER_NAME="$(env_get POSTGRES_USER)"; USER_NAME="${USER_NAME:-sona}"

echo "Restoring $DUMP_FILE into database '$DB' ..."

CONTAINER="$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps -q postgres)"
[ -n "$CONTAINER" ] || { echo "postgres container is not running. Run docker compose up -d first." >&2; exit 1; }

docker cp "$DUMP_FILE" "$CONTAINER:/tmp/sona.dump"
trap 'docker exec "$CONTAINER" rm -f /tmp/sona.dump' EXIT
docker exec "$CONTAINER" pg_restore -U "$USER_NAME" -d "$DB" --clean --if-exists --no-owner /tmp/sona.dump

echo "Restored $DUMP_FILE into database '$DB'."
