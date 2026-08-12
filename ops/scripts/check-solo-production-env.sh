#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-/home/ubuntu/pool-pepepow/ops/env/pool-stratum-solo.env}"

fail() {
  printf 'solo-production-env check failed: %s\n' "$*" >&2
  exit 1
}

[[ -r "${ENV_FILE}" ]] || fail "missing or unreadable env file: ${ENV_FILE}"

require_exact() {
  local key="$1"
  local expected="$2"
  grep -Eq "^[[:space:]]*${key}[[:space:]]*=[[:space:]]*${expected}[[:space:]]*$" "${ENV_FILE}" \
    || fail "${key} must be ${expected}"
}

require_path_contains() {
  local key="$1"
  local fragment="$2"
  local value
  value="$(awk -F= -v key="${key}" '$1 ~ "^[[:space:]]*" key "[[:space:]]*$" {sub(/^[^=]*=/, ""); gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print; exit}' "${ENV_FILE}")"
  [[ -n "${value}" ]] || fail "${key} is missing"
  [[ "${value}" == *"${fragment}"* ]] || fail "${key} must stay in isolated SOLO runtime (${fragment})"
}

require_exact PEPEPOW_POOL_CORE_MINING_MODE solo
require_exact PEPEPOW_POOL_CORE_STRATUM_BIND_PORT 39334
require_exact PEPEPOW_ENABLE_REAL_SUBMITBLOCK true
require_path_contains PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH /solo/
require_path_contains PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_OUTPUT /solo/

max_sends="$(awk -F= '$1 ~ /^[[:space:]]*PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS[[:space:]]*$/ {sub(/^[^=]*=/, ""); gsub(/[[:space:]]/, ""); print; exit}' "${ENV_FILE}")"
[[ "${max_sends}" =~ ^[0-9]+$ ]] || fail "PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS must be a positive integer"
(( max_sends > 0 )) || fail "PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS must be greater than zero"

printf 'solo-production-env: ok (submit enabled, max_sends=%s)\n' "${max_sends}"
