#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

mkdir -p ".runtime/live-stratum"
LOCKFILE=".runtime/live-stratum/payout-autopilot-lite.lock"
RESULT_JSON=".runtime/live-stratum/payout-autopilot-lite-result.json"

exec 9>>"${LOCKFILE}"
if ! flock -n 9; then
  echo "Error: Another instance is running (failed to acquire lock on ${LOCKFILE})." >&2
  exit 1
fi

status="ok"
reviewStatus="unknown"
autoSendEnabled="false"
sendAttempted="false"
finalStatus="unknown"

write_result() {
  local timestamp
  timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  cat <<EOF > "${RESULT_JSON}"
{"timestamp":"${timestamp}","status":"${status}","reviewStatus":"${reviewStatus}","autoSendEnabled":${autoSendEnabled},"sendAttempted":${sendAttempted},"finalStatus":"${finalStatus}"}
EOF
}

# 1. Run accepted-candidates
if ! ./ops/scripts/live-stratum.sh accepted-candidates; then
  status="error"
  finalStatus="failed_accepted_candidates"
  write_result
  exit 1
fi

# 2. Run track-rounds
if ! ./ops/scripts/live-stratum.sh track-rounds; then
  status="error"
  finalStatus="failed_track_rounds"
  write_result
  exit 1
fi

# 3. Run payout-candidates
if ! ./ops/scripts/live-stratum.sh payout-candidates; then
  status="error"
  finalStatus="failed_payout_candidates"
  write_result
  exit 1
fi

# 4. Run payout-carry
if ! ./ops/scripts/live-stratum.sh payout-carry; then
  status="error"
  finalStatus="failed_payout_carry"
  write_result
  exit 1
fi

# 5. Run payout-review-check
review_output=""
review_exit=0
review_output="$(./ops/scripts/live-stratum.sh payout-review-check 2>&1)" || review_exit=$?

status_line="$(printf '%s\n' "${review_output}" | grep '^payout_review_check:' | head -n1)"
status_val="${status_line#payout_review_check: }"
status_val="${status_val//[[:space:]]/}"

if [[ -n "${status_val}" ]]; then
  reviewStatus="${status_val}"
else
  reviewStatus="warning"
fi

carry_line="$(printf '%s\n' "${review_output}" | grep '^carry_audit_status:' | head -n1)"
carry_status="${carry_line#carry_audit_status: }"
carry_status="${carry_status//[[:space:]]/}"

# Fail closed on warning or non-zero exit code of review check
if [[ ${review_exit} -ne 0 || "${reviewStatus}" == "warning" || "${reviewStatus}" == "error" ]]; then
  echo "Error: payout-review-check failed or reported warning: '${reviewStatus}'" >&2
  status="error"
  finalStatus="blocked_review_warning"
  
  ./ops/scripts/live-stratum.sh refresh-payment-confirmations || true
  ./ops/scripts/live-stratum.sh payout-carry-audit || true
  
  write_result
  exit 1
fi

# Fail closed if carry status is not ok
if [[ "${carry_status}" != "ok" ]]; then
  echo "Error: carry audit status is not ok: '${carry_status}'" >&2
  status="error"
  finalStatus="blocked_carry_warning"
  
  ./ops/scripts/live-stratum.sh refresh-payment-confirmations || true
  ./ops/scripts/live-stratum.sh payout-carry-audit || true
  
  write_result
  exit 1
fi

autopilot_send="${PEPEPOW_PAYOUT_AUTOPILOT_SEND:-false}"
if [[ "${autopilot_send}" == "true" ]]; then
  autoSendEnabled="true"
else
  autoSendEnabled="false"
fi

if [[ "${reviewStatus}" == "ready" ]]; then
  if [[ "${autoSendEnabled}" == "true" ]]; then
    sendAttempted="true"
    echo "Autopilot send enabled. Running auto-payout-once..."
    if ! ./ops/scripts/live-stratum.sh auto-payout-once; then
      echo "Error: auto-payout-once failed." >&2
      status="error"
      finalStatus="failed_auto_payout"
      
      ./ops/scripts/live-stratum.sh refresh-payment-confirmations || true
      ./ops/scripts/live-stratum.sh payout-carry-audit || true
      
      write_result
      exit 1
    fi
    finalStatus="sent"
  else
    echo "POOL_PAYOUT_READY auto_send=false"
    finalStatus="skipped_ready"
  fi
elif [[ "${reviewStatus}" == "no-ready-candidates" ]]; then
  echo "No ready candidates. Skipping payout send."
  finalStatus="no_candidates"
else
  # Catch-all for unexpected status
  echo "Error: Unexpected review check status: '${reviewStatus}'" >&2
  status="error"
  finalStatus="blocked_unexpected_status"
  
  ./ops/scripts/live-stratum.sh refresh-payment-confirmations || true
  ./ops/scripts/live-stratum.sh payout-carry-audit || true
  
  write_result
  exit 1
fi

# 6. Always run after send/no-send:
echo "Refreshing payment confirmations..."
if ! ./ops/scripts/live-stratum.sh refresh-payment-confirmations; then
  echo "Warning: refresh-payment-confirmations failed." >&2
  status="warning"
fi

echo "Running carry audit consistency check..."
audit_exit=0
./ops/scripts/live-stratum.sh payout-carry-audit || audit_exit=$?
if [[ ${audit_exit} -ne 0 ]]; then
  echo "Warning: payout-carry-audit failed or reported warnings." >&2
  status="warning"
fi

write_result
echo "Payout autopilot execution completed successfully. Status: ${status}, finalStatus: ${finalStatus}"
