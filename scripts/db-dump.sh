#!/usr/bin/env bash
# Local DB (docker postgres) -> dumps/sona.dump
# Usage (repo root): ./scripts/db-dump.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1  # Git Bash(Windows)에서 /tmp 경로 변환 방지

ROOT="$(cd "$(dirname "$0")/.." && (pwd -W 2>/dev/null || pwd))"  # pwd -W: Git Bash에서 C:/... 형식
ENV_FILE="$ROOT/.env"
COMPOSE_FILE="$ROOT/infra/docker-compose.yml"
OUT_FILE="$ROOT/dumps/sona.dump"

[ -f "$ENV_FILE" ] || { echo ".env not found. Copy .env.example to .env first." >&2; exit 1; }
env_get() { grep -E "^\s*$1\s*=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '\r' | xargs; }
DB="$(env_get POSTGRES_DB)"; DB="${DB:-sona}"
USER_NAME="$(env_get POSTGRES_USER)"; USER_NAME="${USER_NAME:-sona}"

CONTAINER="$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps -q postgres)"
[ -n "$CONTAINER" ] || { echo "postgres container is not running. Run docker compose up -d first." >&2; exit 1; }

docker exec "$CONTAINER" pg_dump -U "$USER_NAME" -d "$DB" -Fc -f /tmp/sona.dump
mkdir -p "$(dirname "$OUT_FILE")"
docker cp "$CONTAINER:/tmp/sona.dump" "$OUT_FILE"
docker exec "$CONTAINER" rm -f /tmp/sona.dump

echo "Dump created: $OUT_FILE ($(wc -c < "$OUT_FILE" | xargs) bytes)"
