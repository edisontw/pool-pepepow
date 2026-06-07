#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run payout-review-check and capture output
output=""
exit_code=0
output="$("${SCRIPT_DIR}/live-stratum.sh" payout-review-check 2>&1)" || exit_code=$?

if [[ ${exit_code} -eq 0 ]]; then
  # Parse the status from the output
  # Example output: payout_review_check: no-ready-candidates OR payout_review_check: ready
  status_line="$(printf '%s\n' "${output}" | grep '^payout_review_check:' | head -n1)"
  status_val="${status_line#payout_review_check: }"
  status_val="${status_val//[[:space:]]/}"

  if [[ "${status_val}" == "ready" ]]; then
    ready_line="$(printf '%s\n' "${output}" | grep '^ready_candidates:' | head -n1)"
    ready_candidates="${ready_line#ready_candidates: }"
    ready_candidates="${ready_candidates//[[:space:]]/}"
    if [[ -z "${ready_candidates}" ]]; then
      ready_candidates="0"
    fi
    printf 'POOL_PAYOUT_READY ready_candidates=%s\n' "${ready_candidates}"
  elif [[ "${status_val}" == "no-ready-candidates" ]]; then
    # Normal state: no output, or one short line if run manually
    if [[ -t 1 ]]; then
      printf 'status=ok ready_candidates=0\n'
    fi
  elif [[ "${status_val}" == "warning" ]]; then
    printf 'POOL_PAYOUT_WARNING status=warning\n'
  else
    # Output structure doesn't match expected pattern
    printf 'POOL_PAYOUT_ERROR exit_code=0\n'
  fi
elif [[ ${exit_code} -eq 1 ]]; then
  printf 'POOL_PAYOUT_WARNING status=warning\n'
else
  printf 'POOL_PAYOUT_ERROR exit_code=%s\n' "${exit_code}"
fi
