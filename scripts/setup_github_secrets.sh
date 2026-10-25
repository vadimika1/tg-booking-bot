#!/usr/bin/env bash
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) not found."
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: scripts/setup_github_secrets.sh <owner/repo>"
  echo "Example: scripts/setup_github_secrets.sh vadimantonovic/tg-booking-bot"
  exit 1
fi

REPO="$1"

required_vars=(
  STAGING_HOST
  STAGING_USER
  STAGING_SSH_KEY
  STAGING_PORT
  STAGING_PROJECT_DIR
  STAGING_HEALTHCHECK_URL
)

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Missing env var: ${var_name}"
    exit 1
  fi
done

for var_name in "${required_vars[@]}"; do
  gh secret set "${var_name}" --repo "${REPO}" --body "${!var_name}"
  echo "Set ${var_name}"
done

echo "GitHub staging secrets are configured for ${REPO}."
