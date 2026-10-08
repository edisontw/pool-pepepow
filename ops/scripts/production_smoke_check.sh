#!/usr/bin/env bash

set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${PEPEPOW_LIVE_STRATUM_RUNTIME_DIR:-${ROOT_DIR}/.runtime/live-stratum}"
FAILURES=0

section() {
  local title="$1"
  shift
  echo "=== ${title} ==="
  if "$@"; then
    echo "PASS: ${title}"
  else
    local status=$?
    echo "FAIL: ${title} (exit ${status})"
    FAILURES=$((FAILURES + 1))
  fi
  echo
}

check_git() {
  local head origin
  head="$(git -C "${ROOT_DIR}" rev-parse HEAD)" || return 1
  origin="$(git -C "${ROOT_DIR}" rev-parse origin/main)" || return 1
  echo "production_sha: ${head}"
  echo "origin_main_sha: ${origin}"
  [[ "${head}" == "${origin}" ]]
}

check_rotation() {
  local common_state=/var/lib/logrotate/status
  local debug_file debug_state pool_exec system_exec
  debug_file="$(mktemp)" || return 1
  debug_state="$(mktemp)" || { rm -f "${debug_file}"; return 1; }
  pool_exec="$(systemctl show pepepow-pool-logrotate.service -p ExecStart --value)"
  system_exec="$(systemctl show logrotate.service -p ExecStart --value)"
  if ! grep -q -- "--state ${common_state}" <<<"${pool_exec}" || ! grep -q 'logrotate /etc/logrotate.conf' <<<"${system_exec}"; then
    echo "Rotation units do not share the standard logrotate state file"
    rm -f "${debug_file}" "${debug_state}"
    return 1
  fi
  if ! logrotate --debug --state "${debug_state}" /etc/logrotate.d/pepepow-pool-runtime >"${debug_file}" 2>&1; then
    tail -n 20 "${debug_file}"
    rm -f "${debug_file}" "${debug_state}"
    return 1
  fi
  if ! systemctl is-active --quiet pepepow-pool-logrotate.timer; then
    echo "Pool logrotate timer is not active"
    rm -f "${debug_file}" "${debug_state}"
    return 1
  fi
  if ! systemctl is-active --quiet logrotate.timer; then
    echo "Standard logrotate timer is not active"
    rm -f "${debug_file}" "${debug_state}"
    return 1
  fi
  echo "Pool and standard logrotate use ${common_state}; debug configuration valid"
  rm -f "${debug_file}" "${debug_state}"
}

check_services() {
  local failed=0 unit
  for unit in pepepowd.service pepepow-pool-stratum.service pepepow-pool-stratum-solo.service pepepow-pool-api.service pepepow-pool-auto-payout.timer pepepow-pool-rounds-refresh.timer pepepow-pool-logrotate.timer; do
    if systemctl is-active --quiet "${unit}"; then
      echo "${unit}: active"
    else
      echo "${unit}: inactive"
      failed=1
    fi
  done
  return "${failed}"
}

check_listeners() {
  local listeners
  listeners="$(ss -lntH 2>/dev/null | awk '$4 ~ /:39333$/ || $4 ~ /:39334$/ || $4 ~ /:8080$/ {print $4}')" || return 1
  printf '%s\n' "${listeners}"
  grep -q ':39333$' <<<"${listeners}" && grep -q ':39334$' <<<"${listeners}" && grep -q ':8080$' <<<"${listeners}"
}

check_daemon() {
  local blockchain network
  blockchain="$(timeout 15 /home/ubuntu/PEPEPOW-cli getblockchaininfo 2>/dev/null)" || return 1
  network="$(timeout 15 /home/ubuntu/PEPEPOW-cli getnetworkinfo 2>/dev/null)" || return 1
  python3 -c 'import json,sys; a=json.load(sys.stdin); assert int(a.get("blocks",0)) > 0; print("chain_height:", a.get("blocks")); print("initial_download:", a.get("initialblockdownload"))' <<<"${blockchain}" || return 1
  python3 -c 'import json,sys; a=json.load(sys.stdin); print("daemon_version:", a.get("subversion", "available"))' <<<"${network}"
}

check_api() {
  local url code
  for url in http://127.0.0.1:8080/api/health http://127.0.0.1:8080/api/pool/summary http://127.0.0.1:8080/api/solo/summary; do
    code="$(curl --max-time 10 -sS -o /dev/null -w '%{http_code}' "${url}")" || return 1
    echo "${code} ${url}"
    [[ "${code}" == 200 ]] || return 1
  done
}

check_payout() {
  python3 - "${ROOT_DIR}" "${RUNTIME_DIR}" <<'PY'
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1])
runtime = Path(sys.argv[2])
sys.path.insert(0, str(root / "ops/scripts"))
import payout_helper

candidates = runtime / "payout-candidates.json"
carry = runtime / "payout-carry-snapshot.json"
payments = runtime / "payments-snapshot.json"
actions = runtime / "payment-actions.jsonl"
review_rc = payout_helper.payout_review_check(candidates, carry, payments)
if review_rc != 0:
    raise SystemExit(f"read-only payout review failed: {review_rc}")
unresolved = payout_helper.get_unresolved_payment_intents(actions)
print("unresolved_payment_intents:", len(unresolved))

data = json.loads(candidates.read_text(encoding="utf-8"))
items = data.get("items", [])
selection = next(((candidate, payout) for candidate in items
                  if candidate.get("status") == "ready_for_manual_review"
                  and isinstance(candidate.get("payouts"), list)
                  for payout in candidate["payouts"]
                  if payout.get("status") in {"pending_manual_payment", "ready_for_wallet_send_preview", "ready"}
                  and payout.get("wallet") and payout.get("amount") is not None), None)
if selection is None:
    raise SystemExit("no ready candidate available for read-only payout preflight")
ready, payout = selection
os.environ["PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS"] = "1"
with tempfile.TemporaryDirectory(prefix="pepepow-smoke-") as temp_dir:
    result_path = Path(temp_dir) / "preflight.json"
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = payout_helper.payout_wallet_send_preflight(
            candidates, actions, result_path, str(ready.get("candidateId") or ready.get("candidate_hash")),
            str(payout["wallet"]), float(payout["amount"]))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    print("wallet_preflight_status:", result.get("status"))
    print("send_attempted:", result.get("sendAttempted"))
    print("send_sent:", result.get("sendSent"))
    if (rc != 0 or result.get("status") not in {"preflight_ok", "blocked_already_paid"}
            or result.get("sendAttempted") is not False or result.get("sendSent") is not False):
        raise SystemExit("read-only payout preflight failed or reported a send")
PY
}

check_snapshots() {
  python3 - "${RUNTIME_DIR}" "${ROOT_DIR}" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
repo = Path(sys.argv[2])
for name in ("rounds-snapshot.json", "payout-candidates.json", "payments-snapshot.json", "payout-carry-snapshot.json", "solo/solo-payout-candidates.json", "solo/solo-payments-snapshot.json"):
    with (root / name).open(encoding="utf-8") as stream:
        json.load(stream)
    print(name + ": valid JSON")

sys.path.insert(0, str(repo / "ops/scripts"))
import payout_helper
for label, candidates_path, actions_path, payments_path, ready_predicate in (
    ("Pool", root / "payout-candidates.json", root / "payment-actions.jsonl", root / "payments-snapshot.json",
     lambda item: item.get("status") == "ready_for_manual_review"),
    ("SOLO", root / "solo/solo-payout-candidates.json", root / "solo/solo-payment-actions.jsonl", root / "solo/solo-payments-snapshot.json",
     lambda item: item.get("lifecycleStatus") == "confirmed" and item.get("eligibleForPayout") is True),
):
    data = json.loads(candidates_path.read_text(encoding="utf-8"))
    paid = payout_helper.load_paid_payment_pairs(actions_path, candidates_path, payments_path)
    unpaid_ready = 0
    for candidate in data.get("items", []):
        if not ready_predicate(candidate):
            continue
        candidate_id = str(candidate.get("candidateId") or candidate.get("candidate_hash") or candidate.get("candidateHash") or "")
        for payout in candidate.get("payouts", []):
            if (payout.get("status") in {"pending_manual_payment", "ready_for_wallet_send_preview", "ready"}
                    and (candidate_id, str(payout.get("wallet") or "")) not in paid):
                unpaid_ready += 1
    print(label + " unpaid_ready:", unpaid_ready)
PY
}

check_disk() {
  df -h /
  python3 - <<'PY'
import json
from pathlib import Path
p=Path('/var/lib/pepepow-pool/resource-health.json')
data=json.loads(p.read_text())
used=float(data.get('rootFilesystemUsedPercent',100))
print('filesystem_used_percent:', used)
assert used < 80, 'root filesystem warning threshold reached'
PY
}

section "GitHub and production revision" check_git
section "Pool and standard logrotate configuration" check_rotation
section "Production services" check_services
section "Pool, SOLO and API listeners" check_listeners
section "Daemon RPC" check_daemon
section "API health and summaries" check_api
section "Read-only payout preflight" check_payout
section "Accounting and payout snapshots" check_snapshots
section "Disk health" check_disk

if (( FAILURES > 0 )); then
  echo "smoke_status: FAIL (${FAILURES} sections)"
  exit 1
fi
echo "smoke_status: PASS"
