#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/pepepow-pool}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "deploy.sh should be run as root on the deployment host." >&2
  exit 1
fi

install -d "${DEPLOY_ROOT}"

rsync -a \
  --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'apps/frontend/site/runtime-config.json' \
  --exclude 'ops/env/*.env' \
  "${REPO_ROOT}/" "${DEPLOY_ROOT}/"

if [[ -x "${DEPLOY_ROOT}/ops/scripts/bootstrap.sh" ]]; then
  "${DEPLOY_ROOT}/ops/scripts/bootstrap.sh"
fi

echo "Deployment sync complete: ${DEPLOY_ROOT}"
