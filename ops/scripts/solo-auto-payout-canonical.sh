#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SOLO_ENV="${REPO_ROOT}/ops/env/pool-stratum-solo.env"

if [[ ! -r "${SOLO_ENV}" ]]; then
  echo "missing readable SOLO environment: ${SOLO_ENV}" >&2
  exit 1
fi

# Preserve the payout enable/allow controls supplied by the parent systemd
# service.  The SOLO Stratum env supplies daemon RPC credentials and SOLO
# runtime settings only; it must not silently enable a disabled payout service.
payout_enabled="${PEPEPOW_ENABLE_REAL_WALLET_PAYOUT:-false}"
allow_any_wallet="${PEPEPOW_AUTO_PAYOUT_ALLOW_ANY_WALLET:-true}"

set -a
# shellcheck disable=SC1090
source "${SOLO_ENV}"
set +a

export PEPEPOW_ENABLE_REAL_WALLET_PAYOUT="${payout_enabled}"
export PEPEPOW_AUTO_PAYOUT_ALLOW_ANY_WALLET="${allow_any_wallet}"
export PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="/var/lib/pepepow-pool"
export PEPEPOW_SOLO_AUTO_PAYOUT_MAX_SENDS="10"

exec "${SCRIPT_DIR}/live-stratum.sh" solo-auto-payout-once
