#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/DA08-VSF}"
LOCK_FILE="${LOCK_FILE:-$APP_DIR/.tmp/user-backfill.lock}"
LOG_DIR="${LOG_DIR:-$APP_DIR/.tmp/user-backfill}"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
LOG_FILE="$LOG_DIR/$TIMESTAMP.log"

mkdir -p "$(dirname "$LOCK_FILE")" "$LOG_DIR"

cd "$APP_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "user-backfill: another run is already in progress" >&2
  exit 1
fi

echo "[$TIMESTAMP] user-backfill: starting periodic reconcile" | tee -a "$LOG_FILE"

docker compose run --rm --no-deps user-backfill | tee -a "$LOG_FILE"

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] user-backfill: completed" | tee -a "$LOG_FILE"
