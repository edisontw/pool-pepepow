#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
LIVE_STRATUM_SCRIPT="${REPO_ROOT}/ops/scripts/live-stratum.sh"

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if ! grep -Fq "${needle}" <<<"${haystack}"; then
    echo "expected output to contain: ${needle}" >&2
    echo "${haystack}" >&2
    exit 1
  fi
}

fixture_dir="${tmpdir}/runtime"
mkdir -p "${fixture_dir}"

python3 - <<'PY' >"${fixture_dir}/share-events.jsonl"
import json

for index in range(20):
    payload = {
        "timestamp": f"2026-05-13T12:00:{index:02d}Z",
        "jobId": f"job-{index:02d}",
        "accepted": True,
        "status": "accepted",
        "targetValidationStatus": "context-valid",
        "jobStatus": "current",
        "localComputedHash": f"{index + 2:x}",
        "shareTargetUsed": "10000",
        "blockTargetUsed": "1",
        "candidatePossible": False,
        "meetsBlockTarget": False,
        "candidatePrepStatus": "candidate-not-triggered",
    }
    print(json.dumps(payload, separators=(",", ":")))
PY

output="$(PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${fixture_dir}" "${LIVE_STRATUM_SCRIPT}" candidate-probability-audit 200)"
assert_contains "${output}" "accepted_share_count: 20"
assert_contains "${output}" "candidate_probability_ratio_scale: 65536"
assert_contains "${output}" "candidate_probability_ratio_scale_source: default-pepepow-65536"
assert_contains "${output}" "median_share_to_block_ratio_raw: 65536"
assert_contains "${output}" "median_share_to_block_ratio_normalized: 1"
assert_contains "${output}" "expected_candidate_count: 20"
assert_contains "${output}" "hash_le_block_but_meetsBlockTarget_not_true: 0"

echo "test_live_stratum_candidate_probability_audit: ok"
