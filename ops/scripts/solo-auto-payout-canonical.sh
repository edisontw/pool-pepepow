#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SOLO_ENV="${REPO_ROOT}/ops/env/pool-stratum-solo.env"
SOLO_RUNTIME="/var/lib/pepepow-pool/solo"
POOL_SNAPSHOT="/var/lib/pepepow-pool/pool-snapshot.json"
ACCEPTED_CANDIDATES="${SOLO_RUNTIME}/accepted-candidates.json"
PAYOUT_CANDIDATES="${SOLO_RUNTIME}/solo-payout-candidates.json"
PAYMENT_ACTIONS="${SOLO_RUNTIME}/solo-payment-actions.jsonl"
PAYMENTS_SNAPSHOT="${SOLO_RUNTIME}/solo-payments-snapshot.json"
AUTO_RESULT="${SOLO_RUNTIME}/solo-auto-payout-once-result.json"

if [[ ! -r "${SOLO_ENV}" ]]; then
  echo "missing readable SOLO environment: ${SOLO_ENV}" >&2
  exit 1
fi

# Preserve payout controls supplied by the parent service. The SOLO env supplies
# daemon RPC credentials and SOLO policy values only; it must not silently
# enable a disabled payout service.
payout_enabled="${PEPEPOW_ENABLE_REAL_WALLET_PAYOUT:-false}"
allow_any_wallet="${PEPEPOW_AUTO_PAYOUT_ALLOW_ANY_WALLET:-true}"

set -a
# shellcheck disable=SC1090
source "${SOLO_ENV}"
set +a

export PEPEPOW_ENABLE_REAL_WALLET_PAYOUT="${payout_enabled}"
export PEPEPOW_AUTO_PAYOUT_ALLOW_ANY_WALLET="${allow_any_wallet}"
export PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="/var/lib/pepepow-pool"
export PEPEPOW_SOLO_AUTO_PAYOUT_MAX_SENDS="${PEPEPOW_SOLO_AUTO_PAYOUT_MAX_SENDS:-10}"

# The minute lifecycle service owns candidate follow-up and canonical accepted
# candidate state. Do not call live-stratum.sh solo-auto-payout-once here: that
# legacy path rebuilds accepted-candidates again and can regress mature records
# when chain context is temporarily incomplete.
python3 "${SCRIPT_DIR}/refresh_solo_maturity.py" \
  --accepted-candidates "${ACCEPTED_CANDIDATES}" \
  --pool-snapshot "${POOL_SNAPSHOT}"

python3 "${SCRIPT_DIR}/solo_payout_helper.py" \
  --accepted-candidates "${ACCEPTED_CANDIDATES}" \
  --output "${PAYOUT_CANDIDATES}" \
  --actions-log "${PAYMENT_ACTIONS}" \
  --payments-snapshot "${PAYMENTS_SNAPSHOT}" \
  --solo-fee-percent "${PEPEPOW_SOLO_FEE_PERCENT:-1.0}" \
  --min-confirmations "${PEPEPOW_SOLO_PAYOUT_MIN_CONFIRMATIONS:-101}"

python3 "${SCRIPT_DIR}/payout_helper.py" auto-payout-once \
  --candidates "${PAYOUT_CANDIDATES}" \
  --actions-log "${PAYMENT_ACTIONS}" \
  --payments-snapshot "${PAYMENTS_SNAPSHOT}" \
  --output "${AUTO_RESULT}" \
  --max-sends "${PEPEPOW_SOLO_AUTO_PAYOUT_MAX_SENDS}" \
  --min-payout 0.00000001
