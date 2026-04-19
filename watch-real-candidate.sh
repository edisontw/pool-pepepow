#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/pool-pepepow}"
RUNTIME_DIR="${REPO_ROOT}/.runtime/live-stratum"
CANDIDATE_LOG="${RUNTIME_DIR}/candidate-events.jsonl"
FOLLOWUP_LOG="${RUNTIME_DIR}/candidate-followup-events.jsonl"
OUTCOME_LOG="${RUNTIME_DIR}/candidate-outcome-events.jsonl"
LIVE_STRATUM="${REPO_ROOT}/ops/scripts/live-stratum.sh"

POLL_SECONDS="${POLL_SECONDS:-5}"
TAIL_COUNT="${TAIL_COUNT:-10}"

if [[ ! -x "${LIVE_STRATUM}" ]]; then
  echo "missing executable: ${LIVE_STRATUM}" >&2
  exit 1
fi

mkdir -p "${RUNTIME_DIR}"
touch "${CANDIDATE_LOG}" "${FOLLOWUP_LOG}" "${OUTCOME_LOG}"

echo "watching real candidates..."
echo "repo_root=${REPO_ROOT}"
echo "candidate_log=${CANDIDATE_LOG}"
echo "poll_seconds=${POLL_SECONDS}"
echo

seen_signature=""

latest_real_candidate_line() {
  python3 - "$CANDIDATE_LOG" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(0)

lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
for raw in reversed(lines):
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        continue
    job_id = str(payload.get("jobId") or "")
    wallet = str(payload.get("wallet") or "")
    worker = str(payload.get("worker") or "")
    if (
        "controlled-drill" in job_id
        or wallet == "controlled-drill"
        or worker == "controlled-drill"
    ):
        continue
    print(raw)
    raise SystemExit(0)
PY
}

candidate_signature() {
  python3 - <<'PY' "$1"
import json, sys
raw = sys.argv[1]
payload = json.loads(raw)
print(
    f'{payload.get("timestamp","")}|'
    f'{payload.get("jobId","")}|'
    f'{payload.get("candidateBlockHash","")}'
)
PY
}

print_candidate_summary() {
  python3 - <<'PY' "$1"
import json, sys
payload = json.loads(sys.argv[1])
print("=== real candidate detected ===")
print(f'timestamp: {payload.get("timestamp")}')
print(f'job_id: {payload.get("jobId")}')
print(f'wallet: {payload.get("wallet")}')
print(f'worker: {payload.get("worker")}')
print(f'candidate_block_hash: {payload.get("candidateBlockHash")}')
print(f'candidate_prep_status: {payload.get("candidatePrepStatus")}')
print(f'dry_run_status: {payload.get("submitblockDryRunStatus")}')
print(f'submit_status: {payload.get("submitblockRealSubmitStatus")}')
print(f'submit_attempted: {payload.get("submitblockAttempted")}')
print(f'submit_sent: {payload.get("submitblockSent")}')
PY
}

while true; do
  raw_line="$(latest_real_candidate_line || true)"

  if [[ -n "${raw_line}" ]]; then
    sig="$(candidate_signature "${raw_line}")"
    if [[ "${sig}" != "${seen_signature}" ]]; then
      seen_signature="${sig}"

      printf '\a'
      echo
      print_candidate_summary "${raw_line}"
      echo
      echo "running follow-up record..."
      "${LIVE_STRATUM}" candidate-followup "${TAIL_COUNT}" --record || true
      echo
      echo "latest outcomes:"
      "${LIVE_STRATUM}" candidate-outcomes "${TAIL_COUNT}" || true
      echo
      echo "latest follow-up events:"
      "${LIVE_STRATUM}" candidate-followup-events "${TAIL_COUNT}" || true
      echo
      echo "watch continues..."
    fi
  fi

  sleep "${POLL_SECONDS}"
done
