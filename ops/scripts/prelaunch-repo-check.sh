#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT_DIR}" ]]; then
  echo "FAIL: not inside a git repository"
  exit 1
fi

cd "${ROOT_DIR}"

failures=0

pass() {
  echo "PASS: $*"
}

fail() {
  echo "FAIL: $*"
  failures=$((failures + 1))
}

run_check() {
  local label="$1"
  shift
  if "$@"; then
    pass "${label}"
  else
    fail "${label}"
  fi
}

tracked_files() {
  git ls-files \
    ':(exclude).runtime/**' \
    ':(exclude)node_modules/**' \
    ':(exclude)**/.venv/**' \
    ':(exclude)**/logs/**' \
    ':(exclude)*.log'
}

run_check "git diff --check" git diff --check
run_check "bash syntax for ops/scripts/*.sh" bash -n ops/scripts/*.sh

echo "Checking tracked runtime files..."
runtime_matches="$(
  git ls-files | grep -E '(^|/)\.runtime/|(^|/)payment-actions\.jsonl$|(^|/)share-events\.jsonl$|\.jsonl$' \
    | grep -v '^tests/fixtures/' || true
)"
if [[ -z "${runtime_matches}" ]]; then
  pass "no tracked runtime JSONL or .runtime files"
else
  echo "${runtime_matches}"
  fail "tracked runtime JSONL or .runtime files found"
fi

echo "Checking likely secrets in tracked files..."
secret_matches="$(
  tracked_files \
    | grep -v '^docs/' \
    | grep -v '^tests/' \
    | xargs -r grep -n -i -E 'rpcpassword=|walletpassphrase|private key|PEPEPOW_RPC_PASSWORD' \
    | grep -v -E 'rpcpassword=(change-me|changeme|example|example-password|drillpass)$' \
    | grep -v -E 'PEPEPOW_RPC_PASSWORD=($|change-me|changeme|example|example-password|your-password|REPLACE_ME)' || true
)"
if [[ -z "${secret_matches}" ]]; then
  pass "no likely secrets in tracked non-doc/test files"
else
  echo "${secret_matches}"
  fail "likely secret text found in tracked files"
fi

echo "Checking frontend wording..."
frontend_matches="$(
  grep -RniE 'guaranteed reward|payable balance|pending reward' apps/frontend/site \
    --exclude-dir=node_modules \
    --exclude-dir=.venv || true
)"
if [[ -z "${frontend_matches}" ]]; then
  pass "no unsupported public payout guarantee wording"
else
  echo "${frontend_matches}"
  fail "unsupported public payout guarantee wording found"
fi

if [[ "${failures}" -eq 0 ]]; then
  echo "SUMMARY: PASS prelaunch repo check"
  exit 0
fi

echo "SUMMARY: FAIL prelaunch repo check (${failures} failure(s))"
exit 1
