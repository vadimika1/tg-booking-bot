#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/tg-booking-bot}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://127.0.0.1:8000/health}"

cd "$PROJECT_DIR"

if [ ! -f .deploy/previous_commit ]; then
  echo "No previous commit found for rollback"
  exit 1
fi

TARGET_COMMIT="$(cat .deploy/previous_commit)"
git checkout "$TARGET_COMMIT"
docker compose up --build -d

curl -fsS "$HEALTHCHECK_URL" >/dev/null
