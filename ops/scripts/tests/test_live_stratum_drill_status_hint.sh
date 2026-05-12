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
  local attempt_count="$3"
  local sent_count="$4"
  local error_count="$5"
  local template_fetch_status="$6"
  local template_rpc_reachable="$7"

  mkdir -p "${fixture_dir}"
  cat >"${fixture_dir}/activity-snapshot.json" <<EOF
{
  "meta": {
    "templateModeEffective": "daemon-template",
    "templateFetchStatus": "${template_fetch_status}",
    "templateDaemonRpcReachable": ${template_rpc_reachable},
    "realSubmitblockEnabled": ${real_submit_enabled},
    "realSubmitblockSendBudget": 1,
    "realSubmitblockSendBudgetRemaining": 1,
    "realSubmitblockAttemptCount": ${attempt_count},
    "realSubmitblockSentCount": ${sent_count},
    "realSubmitblockErrorCount": ${error_count},
    "realSubmitblockLastStatus": "submit-disabled-flag-off",
    "realSubmitblockLastAttemptAt": null,
    "realSubmitblockLastError": null
  }
}
EOF
}

run_drill_status() {
  local fixture_dir="$1"
  PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${fixture_dir}" "${LIVE_STRATUM_SCRIPT}" drill-status
}

assert_has_no_hint() {
  local output="$1"
  if grep -Fq "submit_safety_audit_hint:" <<<"${output}"; then
    echo "expected drill-status output to omit submit_safety_audit_hint" >&2
    echo "${output}" >&2
    exit 1
  fi
}

assert_has_hint() {
  local output="$1"
  if ! grep -Fq "submit_safety_audit_hint: run './ops/scripts/live-stratum.sh submit-safety-audit'" <<<"${output}"; then
    echo "expected drill-status output to include submit_safety_audit_hint" >&2
    echo "${output}" >&2
    exit 1
  fi
}

safe_dir="${tmpdir}/safe"
make_fixture "${safe_dir}" false 0 0 0 ok true
safe_output="$(run_drill_status "${safe_dir}")"
assert_has_no_hint "${safe_output}"

degraded_dir="${tmpdir}/degraded"
make_fixture "${degraded_dir}" false 0 0 0 stale true
degraded_output="$(run_drill_status "${degraded_dir}")"
assert_has_hint "${degraded_output}"

enabled_dir="${tmpdir}/enabled"
make_fixture "${enabled_dir}" true 0 0 0 ok true
enabled_output="$(run_drill_status "${enabled_dir}")"
assert_has_hint "${enabled_output}"

counter_dir="${tmpdir}/counter"
make_fixture "${counter_dir}" false 1 0 0 ok true
counter_output="$(run_drill_status "${counter_dir}")"
assert_has_hint "${counter_output}"

echo "test_live_stratum_drill_status_hint: ok"
