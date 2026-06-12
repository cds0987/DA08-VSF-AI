#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/DA08-VSF}"
CRON_SCHEDULE="${CRON_SCHEDULE:-17 3 * * *}"
RUN_SCRIPT="$APP_DIR/deploy/scripts/run_user_backfill.sh"
MARKER="# DA08 user-backfill reconcile"
CRON_LINE="$CRON_SCHEDULE APP_DIR=$APP_DIR $RUN_SCRIPT"

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

crontab -l 2>/dev/null | grep -vF "$MARKER" | grep -vF "$RUN_SCRIPT" > "$TMP_FILE" || true
{
  cat "$TMP_FILE"
  echo "$MARKER"
  echo "$CRON_LINE"
} | crontab -

echo "Installed cron entry:"
echo "$MARKER"
echo "$CRON_LINE"
