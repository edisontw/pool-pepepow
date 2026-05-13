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

make_stale_fixture() {
  local fixture_dir="$1"
  mkdir -p "${fixture_dir}"
  cat >"${fixture_dir}/candidate-events.jsonl" <<'EOF'
{"timestamp":"2026-05-11T00:10:00Z","jobId":"job-stale","candidateBlockHash":"00000000aaaabbbbccccddddeeeeffff00001111222233334444555566667777","submitblockCandidatePrevhash":"1111111111111111111111111111111111111111111111111111111111111111","submitblockDaemonBestBlockHash":"2222222222222222222222222222222222222222222222222222222222222222","submitblockRealSubmitStatus":"submit-skipped-stale-prevblk","submitblockSent":false,"submitblockAttempted":true,"followupStatus":"not-checked","followupNote":null}
EOF
  cat >"${fixture_dir}/submit-evidence.jsonl" <<'EOF'
{"timestamp":"2026-05-11T00:10:01Z","jobId":"job-stale","submitblockRealSubmitStatus":"submit-not-triggered","submitblockSent":false}
EOF
  cat >"${fixture_dir}/candidate-followup-events.jsonl" <<'EOF'
{"timestamp":"2026-05-11T00:20:00Z","jobId":"job-stale","followupStatus":"no-match-found","followupNote":"candidate-block-hash-not-found-on-local-chain"}
EOF
  cat >"${fixture_dir}/activity-snapshot.json" <<'EOF'
{
  "meta": {
    "templateModeEffective": "daemon-template",
    "templateFetchStatus": "ok",
    "templateDaemonRpcReachable": true
  }
}
EOF
}

make_insufficient_fixture() {
  local fixture_dir="$1"
  mkdir -p "${fixture_dir}"
  cat >"${fixture_dir}/candidate-events.jsonl" <<'EOF'
{"timestamp":"2026-05-09T12:00:00Z","jobId":"job-missing","candidateBlockHash":"000000009999888877776666555544443333222211110000aaaabbbbccccdddd","submitblockRealSubmitStatus":"submit-disabled-flag-off","submitblockSent":false,"submitblockAttempted":false}
EOF
  cat >"${fixture_dir}/submit-evidence.jsonl" <<'EOF'
{"timestamp":"2026-05-09T12:00:01Z","jobId":"job-missing","submitblockRealSubmitStatus":"submit-not-triggered","submitblockSent":false}
EOF
  cat >"${fixture_dir}/activity-snapshot.json" <<'EOF'
{"meta":{"templateModeEffective":"daemon-template","templateFetchStatus":"ok","templateDaemonRpcReachable":true}}
EOF
}

stale_dir="${tmpdir}/stale"
make_stale_fixture "${stale_dir}"
stale_output="$(PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${stale_dir}" "${LIVE_STRATUM_SCRIPT}" candidate-freshness-audit 200)"
assert_contains "${stale_output}" "candidate_events_inspected: 1"
assert_contains "${stale_output}" "submit_evidence_rows_inspected: 1"
assert_contains "${stale_output}" "submit_skipped_stale_prevblk_count_in_window: 1"
assert_contains "${stale_output}" "chain_match_not_found_count_in_window: 1"
assert_contains "${stale_output}" "daemon_best_hash_current: 2222222222222222222222222222222222222222222222222222222222222222"
assert_contains "${stale_output}" "freshness_conclusion: stale-prevblk-observed"

insufficient_dir="${tmpdir}/insufficient"
make_insufficient_fixture "${insufficient_dir}"
insufficient_output="$(PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${insufficient_dir}" "${LIVE_STRATUM_SCRIPT}" candidate-freshness-audit 200)"
assert_contains "${insufficient_output}" "freshness_conclusion: insufficient-fields"
assert_contains "${insufficient_output}" "smallest_future_instrumentation_fields: candidatePrevHash,daemonBestHashAtCandidate,daemonBestHashAtSubmitDecision,templateAgeSeconds,candidateAgeSecondsAtSubmitDecision"

echo "test_live_stratum_candidate_freshness_audit: ok"
