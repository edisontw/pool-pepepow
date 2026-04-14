#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/pepepow-pool}"
DEPLOY_USER="${DEPLOY_USER:-pepepow}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "bootstrap.sh should be run as root on the deployment host." >&2
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip nginx curl rsync

if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
  useradd --system --home "${DEPLOY_ROOT}" --shell /usr/sbin/nologin "${DEPLOY_USER}"
fi

install -d -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" \
  "${DEPLOY_ROOT}" \
  "${DEPLOY_ROOT}/ops/env" \
  "${DEPLOY_ROOT}/apps/frontend/site" \
  /var/lib/pepepow-pool

if [[ ! -d "${DEPLOY_ROOT}/apps/api" ]]; then
  rsync -a --exclude '.git/' "${REPO_ROOT}/" "${DEPLOY_ROOT}/"
  chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${DEPLOY_ROOT}"
fi

python3 -m venv "${DEPLOY_ROOT}/.venv-api"
"${DEPLOY_ROOT}/.venv-api/bin/pip" install --upgrade pip
"${DEPLOY_ROOT}/.venv-api/bin/pip" install -r "${DEPLOY_ROOT}/apps/api/requirements.txt"

[[ -f "${DEPLOY_ROOT}/ops/env/api.env" ]] || cp "${DEPLOY_ROOT}/ops/env/api.env.example" "${DEPLOY_ROOT}/ops/env/api.env"
[[ -f "${DEPLOY_ROOT}/ops/env/frontend.env" ]] || cp "${DEPLOY_ROOT}/ops/env/frontend.env.example" "${DEPLOY_ROOT}/ops/env/frontend.env"
[[ -f "${DEPLOY_ROOT}/ops/env/pool-core.env" ]] || cp "${DEPLOY_ROOT}/ops/env/pool-core.env.example" "${DEPLOY_ROOT}/ops/env/pool-core.env"
[[ -f "${DEPLOY_ROOT}/apps/frontend/site/runtime-config.json" ]] || cp "${DEPLOY_ROOT}/apps/frontend/site/runtime-config.example.json" "${DEPLOY_ROOT}/apps/frontend/site/runtime-config.json"

echo "Bootstrap complete. Review env files in ${DEPLOY_ROOT}/ops/env before enabling services."
