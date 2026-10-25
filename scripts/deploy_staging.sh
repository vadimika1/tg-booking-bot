#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/tg-booking-bot}"
DEPLOY_REF="${DEPLOY_REF:-main}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://127.0.0.1:8000/health}"

cd "$PROJECT_DIR"

mkdir -p .deploy

CURRENT_COMMIT="$(git rev-parse HEAD)"
echo "$CURRENT_COMMIT" > .deploy/previous_commit

git fetch origin "$DEPLOY_REF"
git checkout "$DEPLOY_REF"
git pull --ff-only origin "$DEPLOY_REF"

docker compose up --build -d

if ! curl -fsS "$HEALTHCHECK_URL" >/dev/null; then
  git checkout "$CURRENT_COMMIT"
  docker compose up --build -d
  exit 1
fi

git rev-parse HEAD > .deploy/last_successful_commit
