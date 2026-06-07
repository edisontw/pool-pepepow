#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RETENTION_SCRIPT="${REPO_ROOT}/ops/scripts/runtime-retention.sh"
LIVE_STRATUM_SCRIPT="${REPO_ROOT}/ops/scripts/live-stratum.sh"

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

export PEPEPOW_RETENTION_LOG_MAX_MB=1
export PEPEPOW_RETENTION_JSONL_MAX_MB=1
export PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${tmpdir}"

dd if=/dev/zero of="${tmpdir}/stratum.log" bs=1024 count=1100 2>/dev/null
dd if=/dev/zero of="${tmpdir}/share-events.jsonl" bs=1024 count=1200 2>/dev/null
dd if=/dev/zero of="${tmpdir}/payment-actions.jsonl" bs=1024 count=1300 2>/dev/null
dd if=/dev/zero of="${tmpdir}/small.log" bs=1024 count=10 2>/dev/null
dd if=/dev/zero of="${tmpdir}/activity-snapshot.json" bs=1024 count=10 2>/dev/null

echo "=== Running dry-run check ==="
dry_run_output="$("${RETENTION_SCRIPT}")"
echo "${dry_run_output}"

if ! grep -q "runtime_retention: dry-run" <<<"${dry_run_output}"; then
  echo "FAIL: Expected dry-run status" >&2
  exit 1
fi
if ! grep -q "log_rotate_candidates: 1" <<<"${dry_run_output}"; then
  echo "FAIL: Expected 1 log candidate (stratum.log)" >&2
  exit 1
fi
if ! grep -q "jsonl_archive_candidates: 1" <<<"${dry_run_output}"; then
  echo "FAIL: Expected 1 jsonl candidate (share-events.jsonl)" >&2
  exit 1
fi
if ! grep -q "skipped_critical_jsonl: 1" <<<"${dry_run_output}"; then
  echo "FAIL: Expected 1 skipped critical JSONL" >&2
  exit 1
fi
if ! grep -q "skipped_snapshots: 1" <<<"${dry_run_output}"; then
  echo "FAIL: Expected 1 skipped snapshot" >&2
  exit 1
fi
if ! grep -q "action_required: true" <<<"${dry_run_output}"; then
  echo "FAIL: Expected action_required to be true" >&2
  exit 1
fi

if ls "${tmpdir}"/*.gz &>/dev/null; then
  echo "FAIL: Dry-run created compressed files!" >&2
  exit 1
fi
if [[ "$(stat -c '%s' "${tmpdir}/stratum.log")" -ne 1126400 ]]; then
  echo "FAIL: stratum.log was mutated in dry-run!" >&2
  exit 1
fi

echo "=== Running apply check ==="
apply_output="$("${RETENTION_SCRIPT}" --apply)"
echo "${apply_output}"

if ! grep -q "runtime_retention: applied" <<<"${apply_output}"; then
  echo "FAIL: Expected applied status" >&2
  exit 1
fi
if ! grep -q "rotated_logs: 1" <<<"${apply_output}"; then
  echo "FAIL: Expected 1 rotated log" >&2
  exit 1
fi
if ! grep -q "archived_jsonl: 1" <<<"${apply_output}"; then
  echo "FAIL: Expected 1 archived jsonl" >&2
  exit 1
fi
if ! grep -q "skipped_critical_jsonl: 1" <<<"${apply_output}"; then
  echo "FAIL: Expected 1 skipped critical JSONL" >&2
  exit 1
fi

if [[ ! -f "${tmpdir}/stratum.log" ]] || [[ "$(stat -c '%s' "${tmpdir}/stratum.log")" -ne 0 ]]; then
  echo "FAIL: stratum.log was not rotated/recreated correctly!" >&2
  exit 1
fi
stratum_archive=( "${tmpdir}"/stratum.log.*.gz )
if [[ ! -f "${stratum_archive[0]}" ]]; then
  echo "FAIL: stratum.log archive not found!" >&2
  exit 1
fi

if [[ ! -f "${tmpdir}/share-events.jsonl" ]] || [[ "$(stat -c '%s' "${tmpdir}/share-events.jsonl")" -ne 0 ]]; then
  echo "FAIL: share-events.jsonl was not archived/recreated correctly!" >&2
  exit 1
fi
share_archive=( "${tmpdir}"/share-events.jsonl.*.gz )
if [[ ! -f "${share_archive[0]}" ]]; then
  echo "FAIL: share-events.jsonl archive not found!" >&2
  exit 1
fi

if [[ ! -f "${tmpdir}/payment-actions.jsonl" ]] || [[ "$(stat -c '%s' "${tmpdir}/payment-actions.jsonl")" -ne 1331200 ]]; then
  echo "FAIL: critical payment-actions.jsonl was mutated!" >&2
  exit 1
fi
if ls "${tmpdir}"/payment-actions.jsonl.*.gz &>/dev/null; then
  echo "FAIL: critical payment-actions.jsonl was archived!" >&2
  exit 1
fi

if [[ "$(stat -c '%s' "${tmpdir}/small.log")" -ne 10240 ]]; then
  echo "FAIL: small.log was mutated!" >&2
  exit 1
fi

if [[ "$(stat -c '%s' "${tmpdir}/activity-snapshot.json")" -ne 10240 ]]; then
  echo "FAIL: activity-snapshot.json was mutated!" >&2
  exit 1
fi

echo "=== Running keep count check ==="
for i in {01..10}; do
  touch "${tmpdir}/stratum.log.20260607-0000${i}.gz"
done

apply_output_cleanup="$("${RETENTION_SCRIPT}" --apply)"
echo "${apply_output_cleanup}"

if ! grep -q "removed_old_archives: 4" <<<"${apply_output_cleanup}"; then
  echo "FAIL: Expected to remove 4 old archives, got: ${apply_output_cleanup}" >&2
  exit 1
fi

remaining_archives=( "${tmpdir}"/stratum.log.*.gz )
if [[ ${#remaining_archives[@]} -ne 7 ]]; then
  echo "FAIL: Expected 7 remaining archives, got ${#remaining_archives[@]}" >&2
  exit 1
fi

for i in {01..04}; do
  if [[ -f "${tmpdir}/stratum.log.20260607-0000${i}.gz" ]]; then
    echo "FAIL: stratum.log.20260607-0000${i}.gz should have been deleted!" >&2
    exit 1
  fi
done
for i in {05..10}; do
  if [[ ! -f "${tmpdir}/stratum.log.20260607-0000${i}.gz" ]]; then
    echo "FAIL: stratum.log.20260607-0000${i}.gz should be kept!" >&2
    exit 1
  fi
done

echo "=== Running live-stratum.sh integration check ==="
live_output_dry="$("${LIVE_STRATUM_SCRIPT}" runtime-retention)"
if ! grep -q "runtime_retention: dry-run" <<<"${live_output_dry}"; then
  echo "FAIL: live-stratum.sh integration dry-run failed" >&2
  exit 1
fi

live_output_apply="$("${LIVE_STRATUM_SCRIPT}" runtime-retention --apply)"
if ! grep -q "runtime_retention: applied" <<<"${live_output_apply}"; then
  echo "FAIL: live-stratum.sh integration apply failed" >&2
  exit 1
fi

echo "All tests passed successfully!"
