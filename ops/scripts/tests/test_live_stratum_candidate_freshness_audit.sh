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
{"timestamp":"2026-05-11T00:10:00Z","jobId":"job-stale","candidateBlockHash":"00000000aaaabbbbccccddddeeeeffff00001111222233334444555566667777","candidatePrevHash":"1111111111111111111111111111111111111111111111111111111111111111","templateAgeSeconds":9,"submitblockCandidatePrevhash":"1111111111111111111111111111111111111111111111111111111111111111","submitblockDaemonBestBlockHash":"2222222222222222222222222222222222222222222222222222222222222222","submitblockRealSubmitStatus":"submit-skipped-stale-prevblk","submitblockSent":false,"submitblockAttempted":true,"followupStatus":"not-checked","followupNote":null}
EOF
  cat >"${fixture_dir}/submit-evidence.jsonl" <<'EOF'
{"timestamp":"2026-05-11T00:10:01Z","jobId":"job-stale","submitblockPayloadHash":"00000000aaaabbbbccccddddeeeeffff00001111222233334444555566667777","candidatePrevHash":"1111111111111111111111111111111111111111111111111111111111111111","submitblockRealSubmitStatus":"submit-skipped-stale-prevblk","submitblockSent":false,"realSubmitblockEnabled":true,"daemonBestHashAtSubmitDecision":"3333333333333333333333333333333333333333333333333333333333333333","candidatePrevHashMatchesDaemonBestAtSubmitDecision":false,"candidateFreshnessStatus":"stale-prevblk","templateAgeSeconds":9,"candidateAgeSecondsAtSubmitDecision":14}
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

make_submit_disabled_fixture() {
  local fixture_dir="$1"
  mkdir -p "${fixture_dir}"
  cat >"${fixture_dir}/candidate-events.jsonl" <<'EOF'
{"timestamp":"2026-05-13T11:09:54Z","jobId":"job-disabled","candidateBlockHash":"0000000305c7619c493a0f14cd6802173898955621e6176419790311d86c4280","candidatePrevHash":"000000027116173c9fd6b5c5d70be422af9aacd698589f5caa844cfc0a5e93c1","templateAgeSeconds":13,"submitblockRealSubmitStatus":"submit-disabled-flag-off","submitblockSent":false,"submitblockAttempted":false}
EOF
  cat >"${fixture_dir}/submit-evidence.jsonl" <<'EOF'
{"timestamp":"2026-05-13T11:09:55Z","jobId":"job-disabled","submitblockRealSubmitStatus":"submit-not-triggered","submitblockSent":false}
EOF
  cat >"${fixture_dir}/activity-snapshot.json" <<'EOF'
{"meta":{"templateModeEffective":"daemon-template","templateFetchStatus":"ok","templateDaemonRpcReachable":true}}
EOF
}

make_ready_fixture() {
  local fixture_dir="$1"
  mkdir -p "${fixture_dir}"
  cat >"${fixture_dir}/candidate-events.jsonl" <<'EOF'
{"timestamp":"2026-05-13T12:20:00Z","jobId":"job-ready","candidateBlockHash":"00000000feedfacecafebeef111122223333444455556666777788889999aaaa","candidatePrevHash":"00000000aaaabbbbccccddddeeeeffff11112222333344445555666677778888","templateAgeSeconds":4,"submitblockRealSubmitStatus":"submit-not-triggered","submitblockSent":false,"submitblockAttempted":false}
EOF
  cat >"${fixture_dir}/submit-evidence.jsonl" <<'EOF'
{"timestamp":"2026-05-13T12:20:01Z","jobId":"job-ready","submitblockRealSubmitStatus":"submit-not-triggered","submitblockSent":false}
EOF
  cat >"${fixture_dir}/activity-snapshot.json" <<'EOF'
{"meta":{"templateModeEffective":"daemon-template","templateFetchStatus":"ok","templateDaemonRpcReachable":true,"realSubmitblockEnabled":true,"realSubmitblockSendBudgetRemaining":1}}
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
assert_contains "${stale_output}" "latest_candidate_has_attribution: true"
assert_contains "${stale_output}" "latest_candidate_template_age_seconds: 9"
assert_contains "${stale_output}" "submit_decision_fields_expected: true"
assert_contains "${stale_output}" "latest_submit_has_decision_attribution: true"
assert_contains "${stale_output}" "latest_submit_candidate_freshness_status: stale-prevblk"
assert_contains "${stale_output}" "latest_submit_prevhash_matches_daemon_best: false"
assert_contains "${stale_output}" "latest_submit_classification_source: submit-evidence"
assert_contains "${stale_output}" "latest_submit_readiness_status: stale-prevblk"
assert_contains "${stale_output}" "attribution_note: decision-attribution-present"
assert_contains "${stale_output}" "freshness_conclusion: stale-prevblk-observed"

insufficient_dir="${tmpdir}/insufficient"
make_insufficient_fixture "${insufficient_dir}"
insufficient_output="$(PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${insufficient_dir}" "${LIVE_STRATUM_SCRIPT}" candidate-freshness-audit 200)"
assert_contains "${insufficient_output}" "latest_candidate_has_attribution: false"
assert_contains "${insufficient_output}" "latest_candidate_template_age_seconds: None"
assert_contains "${insufficient_output}" "submit_decision_fields_expected: false"
assert_contains "${insufficient_output}" "latest_submit_has_decision_attribution: false"
assert_contains "${insufficient_output}" "latest_submit_candidate_freshness_status: unknown"
assert_contains "${insufficient_output}" "latest_submit_prevhash_matches_daemon_best: null"
assert_contains "${insufficient_output}" "latest_submit_classification_source: none"
assert_contains "${insufficient_output}" "latest_submit_readiness_status: disabled"
assert_contains "${insufficient_output}" "attribution_note: candidate-attribution-missing"
assert_contains "${insufficient_output}" "freshness_conclusion: insufficient-fields"
assert_contains "${insufficient_output}" "smallest_future_instrumentation_fields: candidatePrevHash,daemonBestHashAtCandidate,daemonBestHashAtSubmitDecision,templateAgeSeconds,candidateAgeSecondsAtSubmitDecision"

submit_disabled_dir="${tmpdir}/submit-disabled"
make_submit_disabled_fixture "${submit_disabled_dir}"
submit_disabled_output="$(PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${submit_disabled_dir}" "${LIVE_STRATUM_SCRIPT}" candidate-freshness-audit 200)"
assert_contains "${submit_disabled_output}" "latest_candidate_prevhash: 000000027116173c9fd6b5c5d70be422af9aacd698589f5caa844cfc0a5e93c1"
assert_contains "${submit_disabled_output}" "latest_candidate_has_attribution: true"
assert_contains "${submit_disabled_output}" "latest_candidate_template_age_seconds: 13"
assert_contains "${submit_disabled_output}" "latest_submit_status: submit-disabled-flag-off"
assert_contains "${submit_disabled_output}" "submit_decision_fields_expected: false"
assert_contains "${submit_disabled_output}" "latest_submit_has_decision_attribution: false"
assert_contains "${submit_disabled_output}" "latest_submit_candidate_freshness_status: unknown"
assert_contains "${submit_disabled_output}" "latest_submit_prevhash_matches_daemon_best: null"
assert_contains "${submit_disabled_output}" "latest_submit_classification_source: none"
assert_contains "${submit_disabled_output}" "latest_submit_readiness_status: disabled"
assert_contains "${submit_disabled_output}" "attribution_note: candidate-attribution-present-submit-disabled"

ready_dir="${tmpdir}/ready"
make_ready_fixture "${ready_dir}"
ready_output="$(PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${ready_dir}" "${LIVE_STRATUM_SCRIPT}" candidate-freshness-audit 200)"
assert_contains "${ready_output}" "latest_submit_status: submit-not-triggered"
assert_contains "${ready_output}" "latest_submit_candidate_freshness_status: unknown"
assert_contains "${ready_output}" "latest_submit_readiness_status: ready"

fallback_dir="${tmpdir}/fallback"
mkdir -p "${fallback_dir}"
cat >"${fallback_dir}/candidate-events.jsonl" <<'EOF'
{"timestamp":"2026-05-13T12:42:48Z","jobId":"job-fallback","candidateBlockHash":"00000001c4a0a4edf6ae65cadac19d3404ed3d750e49d012b558366d3771a85b","candidatePrevHash":"000000047731b207515f73a0905e0255aaf52389d3342708740ab688ec3c3762","templateAgeSeconds":8,"submitblockRealSubmitStatus":"submit-skipped-stale-prevblk","submitblockSent":false,"submitblockAttempted":false}
EOF
cat >"${fallback_dir}/submit-evidence.jsonl" <<'EOF'
{"timestamp":"2026-05-13T12:42:48Z","jobId":"job-fallback","localComputedHash":"00000001c4a0a4edf6ae65cadac19d3404ed3d750e49d012b558366d3771a85b","candidatePrevHash":"000000047731b207515f73a0905e0255aaf52389d3342708740ab688ec3c3762","submitblockRealSubmitStatus":"submit-skipped-stale-prevblk","submitblockSent":false,"daemonBestHashAtSubmitDecision":"0000000399cd89e59fbdd50900e57dc2f136cbb8b832fa46c58d506aec82d821","templateAgeSeconds":8,"candidateAgeSecondsAtSubmitDecision":0}
EOF
cat >"${fallback_dir}/activity-snapshot.json" <<'EOF'
{"meta":{"templateModeEffective":"daemon-template","templateFetchStatus":"ok","templateDaemonRpcReachable":true}}
EOF
fallback_output="$(PEPEPOW_LIVE_STRATUM_RUNTIME_DIR="${fallback_dir}" "${LIVE_STRATUM_SCRIPT}" candidate-freshness-audit 200)"
assert_contains "${fallback_output}" "latest_candidate_hash: 00000001c4a0a4edf6ae65cadac19d3404ed3d750e49d012b558366d3771a85b"
assert_contains "${fallback_output}" "submit_decision_fields_expected: true"
assert_contains "${fallback_output}" "latest_submit_has_decision_attribution: true"
assert_contains "${fallback_output}" "latest_submit_candidate_freshness_status: unknown"
assert_contains "${fallback_output}" "latest_submit_prevhash_matches_daemon_best: null"
assert_contains "${fallback_output}" "latest_submit_classification_source: none"
assert_contains "${fallback_output}" "latest_submit_readiness_status: unknown"
assert_contains "${fallback_output}" "attribution_note: decision-attribution-present"

echo "test_live_stratum_candidate_freshness_audit: ok"
