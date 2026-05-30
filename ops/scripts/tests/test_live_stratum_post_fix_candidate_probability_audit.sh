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

# Generate simulated launch.env
echo "PEPEPOW_POOL_CORE_STRATUM_WIRE_DIFFICULTY_SCALE=65536" > "${fixture_dir}/launch.env"

python3 - <<'PY' >"${fixture_dir}/share-events.jsonl"
import json

# Rows before cutoff
for index in range(5):
    payload = {
        "timestamp": f"2026-05-28T14:00:{index:02d}Z",
        "jobId": f"job-before-{index:02d}",
        "accepted": True,
        "status": "accepted",
        "targetValidationStatus": "context-valid",
        "jobStatus": "current",
        "localComputedHash": f"{index + 2:x}",
        "shareTargetUsed": "1000000000000000",
        "blockTargetUsed": "1000000000000000",
        "meetsBlockTarget": False,
        "candidatePrepStatus": "candidate-not-triggered",
    }
    print(json.dumps(payload, separators=(",", ":")))

# Rows after cutoff (10 accepted shares)
for index in range(10):
    payload = {
        "timestamp": f"2026-05-28T16:00:{index:02d}Z",
        "jobId": f"job-after-{index:02d}",
        "accepted": True,
        "status": "accepted",
        "targetValidationStatus": "context-valid",
        "jobStatus": "current",
        "localComputedHash": f"{index + 2:x}",
        "shareTargetUsed": "10000", # share target is 65536 times block target
        "blockTargetUsed": "1",
        "meetsBlockTarget": False,
        "candidatePrepStatus": "candidate-not-triggered",
        "difficulty": 0.00025
    }
    print(json.dumps(payload, separators=(",", ":")))
PY

output="$(PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${fixture_dir}" "${LIVE_STRATUM_SCRIPT}" post-fix-candidate-probability-audit 200)"
assert_contains "${output}" "Rows before cutoff:      5"
assert_contains "${output}" "Rows after cutoff:       10"
assert_contains "${output}" "Post-cutoff accepted shares:    10"
assert_contains "${output}" "Expected candidates (estimation):   10.000000"
assert_contains "${output}" "Conclusion: CANDIDATE DROUGHT SUSPICIOUS"

# Setup another test case with expected candidates = 1.5 (which is >= 1.0)
# and observed candidates = 0, but poisson_p_zero = exp(-1.5) = 22.3% (which is >= 1%)
# to verify Conclusion: CANDIDATE LIVENESS WARNING
python3 - <<'PY' >"${fixture_dir}/share-events.jsonl"
import json
for index in range(3):
    payload = {
        "timestamp": f"2026-05-28T16:00:{index:02d}Z",
        "jobId": f"job-after-{index:02d}",
        "accepted": True,
        "status": "accepted",
        "targetValidationStatus": "context-valid",
        "jobStatus": "current",
        "localComputedHash": f"{index + 2:x}",
        "shareTargetUsed": "18000",
        "blockTargetUsed": "1",
        "meetsBlockTarget": False,
        "candidatePrepStatus": "candidate-not-triggered",
        "difficulty": 0.00025
    }
    print(json.dumps(payload, separators=(",", ":")))
PY

# Add a mock candidate event to test latest candidate timestamp tracking
echo '{"timestamp": "2026-05-27T10:00:00Z", "candidateBlockHash": "abcdef"}' > "${fixture_dir}/candidate-events.jsonl"

output2="$(PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${fixture_dir}" "${LIVE_STRATUM_SCRIPT}" post-fix-candidate-probability-audit 200)"
assert_contains "${output2}" "Conclusion: CANDIDATE LIVENESS WARNING"
assert_contains "${output2}" "Detail: Latest candidate timestamp: 2026-05-27T10:00:00Z"
assert_contains "${output2}" "not enough evidence to reopen target math, but candidate liveness has not advanced."

echo "test_live_stratum_post_fix_candidate_probability_audit: ok"
