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

# Create active files
dd if=/dev/zero of="${tmpdir}/stratum.log" bs=1024 count=1100 2>/dev/null
dd if=/dev/zero of="${tmpdir}/submit-evidence.jsonl" bs=1024 count=1200 2>/dev/null
dd if=/dev/zero of="${tmpdir}/payment-actions.jsonl" bs=1024 count=1300 2>/dev/null
dd if=/dev/zero of="${tmpdir}/payout-candidates.json" bs=1024 count=10 2>/dev/null
dd if=/dev/zero of="${tmpdir}/share-events.jsonl" bs=1024 count=10 2>/dev/null

# Create share event segments with sequential timestamps (oldest to newest)
for i in {1..5}; do
  touch "${tmpdir}/share-events.${i}.jsonl"
  sleep 0.1
done

echo "=== Running dry-run check ==="
dry_run_output="$("${RETENTION_SCRIPT}")"
echo "${dry_run_output}"

# Verify dry-run outputs
if ! grep -q "runtime_retention: dry-run" <<<"${dry_run_output}"; then
  echo "FAIL: Expected dry-run status" >&2
  exit 1
fi
if ! grep -q "log_rotate_candidates: 1" <<<"${dry_run_output}"; then
  echo "FAIL: Expected 1 log candidate (stratum.log)" >&2
  exit 1
fi
if ! grep -q "jsonl_archive_candidates: 1" <<<"${dry_run_output}"; then
  echo "FAIL: Expected 1 jsonl candidate (submit-evidence.jsonl)" >&2
  exit 1
fi
if ! grep -q "share_segment_archive_candidates: 2" <<<"${dry_run_output}"; then
  echo "FAIL: Expected 2 share segment candidates (share-events.1 and .2)" >&2
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

# Verify dry-run wrote nothing
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
if ! grep -q "log_rotate_candidates: 1" <<<"${apply_output}"; then
  echo "FAIL: Expected 1 log candidate" >&2
  exit 1
fi
if ! grep -q "jsonl_archive_candidates: 1" <<<"${apply_output}"; then
  echo "FAIL: Expected 1 jsonl candidate" >&2
  exit 1
fi
if ! grep -q "share_segment_archive_candidates: 2" <<<"${apply_output}"; then
  echo "FAIL: Expected 2 share segment candidates" >&2
  exit 1
fi

# Verify mutations
# stratum.log rotated to .gz, active recreated empty
if [[ ! -f "${tmpdir}/stratum.log" ]] || [[ "$(stat -c '%s' "${tmpdir}/stratum.log")" -ne 0 ]]; then
  echo "FAIL: stratum.log was not rotated/recreated correctly!" >&2
  exit 1
fi
stratum_archive=( "${tmpdir}"/stratum.log.*.gz )
if [[ ! -f "${stratum_archive[0]}" ]]; then
  echo "FAIL: stratum.log archive not found!" >&2
  exit 1
fi

# submit-evidence.jsonl rotated to .gz, active recreated empty
if [[ ! -f "${tmpdir}/submit-evidence.jsonl" ]] || [[ "$(stat -c '%s' "${tmpdir}/submit-evidence.jsonl")" -ne 0 ]]; then
  echo "FAIL: submit-evidence.jsonl was not rotated/recreated correctly!" >&2
  exit 1
fi
submit_archive=( "${tmpdir}"/submit-evidence.jsonl.*.gz )
if [[ ! -f "${submit_archive[0]}" ]]; then
  echo "FAIL: submit-evidence.jsonl archive not found!" >&2
  exit 1
fi

# payment-actions.jsonl (critical) remains untouched
if [[ ! -f "${tmpdir}/payment-actions.jsonl" ]] || [[ "$(stat -c '%s' "${tmpdir}/payment-actions.jsonl")" -ne 1331200 ]]; then
  echo "FAIL: critical payment-actions.jsonl was mutated!" >&2
  exit 1
fi

# payout-candidates.json remains untouched
if [[ ! -f "${tmpdir}/payout-candidates.json" ]] || [[ "$(stat -c '%s' "${tmpdir}/payout-candidates.json")" -ne 10240 ]]; then
  echo "FAIL: payout-candidates.json was mutated!" >&2
  exit 1
fi

# share-events.jsonl remains untouched (under threshold)
if [[ ! -f "${tmpdir}/share-events.jsonl" ]] || [[ "$(stat -c '%s' "${tmpdir}/share-events.jsonl")" -ne 10240 ]]; then
  echo "FAIL: active share-events.jsonl was mutated!" >&2
  exit 1
fi

# share-events.1 and .2 should be gzipped
if [[ -f "${tmpdir}/share-events.1.jsonl" ]] || [[ ! -f "${tmpdir}/share-events.1.jsonl.gz" ]]; then
  echo "FAIL: share-events.1.jsonl was not gzipped!" >&2
  exit 1
fi
if [[ -f "${tmpdir}/share-events.2.jsonl" ]] || [[ ! -f "${tmpdir}/share-events.2.jsonl.gz" ]]; then
  echo "FAIL: share-events.2.jsonl was not gzipped!" >&2
  exit 1
fi

# share-events.3, .4, .5 (latest 3) should remain uncompressed
for i in 3 4 5; do
  if [[ ! -f "${tmpdir}/share-events.${i}.jsonl" ]] || [[ -f "${tmpdir}/share-events.${i}.jsonl.gz" ]]; then
    echo "FAIL: share-events.${i}.jsonl should remain uncompressed!" >&2
    exit 1
  fi
done

echo "=== Running compressed archives keep count check ==="
# We have 2 archives in the share-events group: share-events.1.jsonl.gz and share-events.2.jsonl.gz
# Create 10 pre-existing dummy archives in the share-events group
# Using timestamped naming so they sort chronologically
for i in {01..10}; do
  touch "${tmpdir}/share-events.jsonl.20260607-0000${i}.gz"
  sleep 0.05
done

# Now we should have 12 archives in the share-events group (10 dummy + 2 segment archives)
# Let's run apply again. It should remove the 5 oldest archives to keep exactly 7.
apply_output_cleanup="$("${RETENTION_SCRIPT}" --apply)"
echo "${apply_output_cleanup}"

if ! grep -q "removed_old_archives: 5" <<<"${apply_output_cleanup}"; then
  echo "FAIL: Expected to remove 5 old archives, got: ${apply_output_cleanup}" >&2
  exit 1
fi

remaining_archives=( "${tmpdir}"/share-events*.gz )
if [[ ${#remaining_archives[@]} -ne 7 ]]; then
  echo "FAIL: Expected 7 remaining archives, got ${#remaining_archives[@]}" >&2
  exit 1
fi

echo "=== Running live-stratum.sh integration check ==="
live_output_dry="$("${LIVE_STRATUM_SCRIPT}" runtime-retention)"
if ! grep -q "runtime_retention: dry-run" <<<"${live_output_dry}"; then
  echo "FAIL: live-stratum.sh integration dry-run failed" >&2
  exit 1
fi

echo "All tests passed successfully!"
