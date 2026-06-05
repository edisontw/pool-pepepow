#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
LIVE_STRATUM_SCRIPT="${REPO_ROOT}/ops/scripts/live-stratum.sh"

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

make_fixture() {
  local fixture_dir="$1"
  local real_submit_enabled="$2"
  local budget="$3"
  local template_fetch_status="$4"
  local template_rpc_reachable="$5"

  mkdir -p "${fixture_dir}"
  cat >"${fixture_dir}/activity-snapshot.json" <<EOF
{
  "meta": {
    "templateModeEffective": "daemon-template",
    "templateFetchStatus": "${template_fetch_status}",
    "templateDaemonRpcReachable": ${template_rpc_reachable},
    "realSubmitblockEnabled": ${real_submit_enabled},
    "realSubmitblockSendBudget": ${budget},
    "realSubmitblockSendBudgetRemaining": ${budget},
    "realSubmitblockAttemptCount": 0,
    "realSubmitblockSentCount": 0,
    "realSubmitblockErrorCount": 0
  }
}
EOF
}

# 1. Test invalid preflight (real_submit_enabled is true)
invalid_dir="${tmpdir}/invalid"
make_fixture "${invalid_dir}" true 1 ok true
if PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${invalid_dir}" SYSTEMCTL_BIN="true" "${LIVE_STRATUM_SCRIPT}" controlled-submit-drill-once 5 2; then
  echo "Expected preflight to fail when real_submit_enabled is true" >&2
  exit 1
fi

# 2. Test valid preflight (preflight succeeds, then arming fails because of false systemctl bin)
valid_dir="${tmpdir}/valid"
make_fixture "${valid_dir}" false 1 ok true
# Mock SYSTEMCTL_BIN to return false to verify that it proceeds past preflight check to arming
output=$(PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${valid_dir}" SYSTEMCTL_BIN="/bin/false" "${LIVE_STRATUM_SCRIPT}" controlled-submit-drill-once 5 2 2>&1 || true)
if grep -q "Preflight validation failed" <<<"${output}"; then
  echo "Expected preflight to succeed when parameters are valid, but got: ${output}" >&2
  exit 1
fi

echo "test_live_stratum_controlled_submit_drill_preflight: ok"
