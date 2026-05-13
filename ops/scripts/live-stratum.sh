#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
POOL_CORE_DIR="${REPO_ROOT}/apps/pool-core"
RUNTIME_DIR="${PEPEPOW_LIVE_STRATUM_RUNTIME_DIR:-${REPO_ROOT}/.runtime/live-stratum}"
PID_FILE="${RUNTIME_DIR}/stratum.pid"
LOG_FILE="${RUNTIME_DIR}/stratum.log"
SHARE_LOG="${RUNTIME_DIR}/share-events.jsonl"
CANDIDATE_EVENT_LOG="${RUNTIME_DIR}/candidate-events.jsonl"
CANDIDATE_OUTCOME_EVENT_LOG="${RUNTIME_DIR}/candidate-outcome-events.jsonl"
# shellcheck disable=SC2034
FOLLOWUP_EVENT_LOG="${RUNTIME_DIR}/candidate-followup-events.jsonl"
SUBMIT_EVIDENCE_LOG="${RUNTIME_DIR}/submit-evidence.jsonl"
NOTIFY_EVIDENCE_LOG="${RUNTIME_DIR}/notify-evidence.jsonl"
ACTIVITY_SNAPSHOT="${RUNTIME_DIR}/activity-snapshot.json"
LAUNCH_ENV_FILE="${RUNTIME_DIR}/launch.env"
SYSTEMD_UNIT_NAME="pepepow-pool-stratum.service"

SUBCOMMAND="${1:-status}"

detect_default_host() {
  local detected
  detected="$(curl -fsS --max-time 2 ifconfig.me 2>/dev/null || true)"
  if [[ "${detected}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf '%s\n' "${detected}"
    return
  fi
  detected="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -n "${detected}" ]]; then
    printf '%s\n' "${detected}"
    return
  fi
  printf '127.0.0.1\n'
}

detect_node_bin() {
  local candidate
  for candidate in \
    "${NODE_BIN:-}" \
    "/home/ubuntu/.local/node-v16.20.2-linux-arm64/bin/node" \
    "/home/ubuntu/.local/node-v22.21.1-linux-arm64/bin/node" \
    "$(command -v node 2>/dev/null || true)" \
    "$(command -v nodejs 2>/dev/null || true)" \
    "/home/ubuntu/.windsurf-server/bin/16cc024632923bc387171d59cf5638057d4c8918/node" \
    "/home/ubuntu/.antigravity-server/bin/1.16.5-1504c8cc4b34dbfbb4a97ebe954b3da2b5634516/node" \
    "/home/ubuntu/.cache/ms-playwright-go/1.50.1/node"
  do
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

PORT=""
PUBLIC_HOST=""
BIND_HOST=""
SHARE_DIFFICULTY=""
ESTIMATED_HASHRATE_SHARE_DIFFICULTY=""
JOB_INTERVAL_SECONDS=""
SNAPSHOT_INTERVAL_SECONDS=""
LOG_ROTATE_BYTES=""
NOTIFY_DEBUG_CAPTURE_LIMIT=""
TEMPLATE_MODE=""
TEMPLATE_FETCH_INTERVAL_SECONDS=""
TEMPLATE_JOB_TTL_SECONDS=""
TEMPLATE_JOB_CACHE_SIZE=""
REAL_SUBMITBLOCK_ENABLED=""
REAL_SUBMITBLOCK_MAX_SENDS=""
RPC_HOST=""
RPC_PORT=""
RPC_URL=""
RPC_USER=""
RPC_PASSWORD=""
RPC_TIMEOUT_SECONDS=""
VARDIFF_ENABLED=""
LOW_DIFF_SHARE_FULL_LOG_EVERY_N=""
STRATUM_WIRE_DIFFICULTY_SCALE=""
VARDIFF_INITIAL_DIFFICULTY=""
VARDIFF_MIN_DIFFICULTY=""
VARDIFF_MAX_DIFFICULTY=""
VARDIFF_TARGET_SHARE_INTERVAL_SECONDS=""
VARDIFF_RETARGET_INTERVAL_SECONDS=""
VARDIFF_MIN_SHARES=""
VARDIFF_FAST_SHARE_INTERVAL_SECONDS=""
VARDIFF_SLOW_SHARE_INTERVAL_SECONDS=""
LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND="false"
LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND_REASON=""

set_effective_defaults() {
  local detected_rpc_host detected_rpc_port
  detected_rpc_host="${PEPEPOWD_RPC_HOST:-127.0.0.1}"
  detected_rpc_port="${PEPEPOWD_RPC_PORT:-8834}"
  PORT="${PEPEPOW_POOL_CORE_STRATUM_BIND_PORT:-39333}"
  PUBLIC_HOST="${PEPEPOW_POOL_CORE_STRATUM_HOST:-$(detect_default_host)}"
  BIND_HOST="${PEPEPOW_POOL_CORE_STRATUM_BIND_HOST:-0.0.0.0}"
  SHARE_DIFFICULTY="${PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY:-1.0}"
  ESTIMATED_HASHRATE_SHARE_DIFFICULTY="${PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY:-${SHARE_DIFFICULTY}}"
  JOB_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS:-5}"
  SNAPSHOT_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS:-1}"
  LOG_ROTATE_BYTES="${PEPEPOW_LIVE_STRATUM_LOG_ROTATE_BYTES:-33554432}"
  NOTIFY_DEBUG_CAPTURE_LIMIT="${PEPEPOW_POOL_CORE_NOTIFY_DEBUG_CAPTURE_LIMIT:-0}"
  TEMPLATE_MODE="${PEPEPOW_POOL_CORE_TEMPLATE_MODE:-synthetic}"
  TEMPLATE_FETCH_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_TEMPLATE_FETCH_INTERVAL_SECONDS:-15}"
  TEMPLATE_JOB_TTL_SECONDS="${PEPEPOW_POOL_CORE_TEMPLATE_JOB_TTL_SECONDS:-180}"
  TEMPLATE_JOB_CACHE_SIZE="${PEPEPOW_POOL_CORE_TEMPLATE_JOB_CACHE_SIZE:-64}"
  REAL_SUBMITBLOCK_ENABLED="${PEPEPOW_ENABLE_REAL_SUBMITBLOCK:-false}"
  REAL_SUBMITBLOCK_MAX_SENDS="${PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS:-1}"
  CLEAN_JOBS_LEGACY="${PEPEPOW_STRATUM_NOTIFY_CLEAN_JOBS_LEGACY:-false}"
  VERSION_SOURCE_ORDER="${PEPEPOW_HEADER_VERSION_SOURCE_ORDER_ENABLED:-false}"
  RPC_HOST="${detected_rpc_host}"
  RPC_PORT="${detected_rpc_port}"
  RPC_URL="${PEPEPOWD_RPC_URL:-http://${detected_rpc_host}:${detected_rpc_port}}"
  RPC_USER="${PEPEPOWD_RPC_USER:-}"
  RPC_PASSWORD="${PEPEPOWD_RPC_PASSWORD:-}"
  RPC_TIMEOUT_SECONDS="${PEPEPOWD_RPC_TIMEOUT_SECONDS:-5}"
  VARDIFF_ENABLED="${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_ENABLED:-false}"
  LOW_DIFF_SHARE_FULL_LOG_EVERY_N="${PEPEPOW_POOL_CORE_LOW_DIFF_SHARE_FULL_LOG_EVERY_N:-1}"
  STRATUM_WIRE_DIFFICULTY_SCALE="${PEPEPOW_POOL_CORE_STRATUM_WIRE_DIFFICULTY_SCALE:-65536}"
  VARDIFF_INITIAL_DIFFICULTY="${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_INITIAL_DIFFICULTY:-0.1}"
  VARDIFF_MIN_DIFFICULTY="${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_DIFFICULTY:-0.01}"
  VARDIFF_MAX_DIFFICULTY="${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MAX_DIFFICULTY:-64}"
  VARDIFF_TARGET_SHARE_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_TARGET_SHARE_INTERVAL_SECONDS:-15}"
  VARDIFF_RETARGET_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_RETARGET_INTERVAL_SECONDS:-60}"
  VARDIFF_MIN_SHARES="${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_SHARES:-4}"
  VARDIFF_FAST_SHARE_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_FAST_SHARE_INTERVAL_SECONDS:-8}"
  VARDIFF_SLOW_SHARE_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_SLOW_SHARE_INTERVAL_SECONDS:-25}"
}

ensure_runtime_dir() {
  mkdir -p "${RUNTIME_DIR}"
}

is_localhost_host() {
  local host
  host="${1:-}"
  case "${host}" in
    127.0.0.1|localhost|::1)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

set_launch_env_suspicious_localhost_bind() {
  local bind_host bind_port public_host
  bind_host="${1:-}"
  bind_port="${2:-}"
  public_host="${3:-}"
  LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND="false"
  LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND_REASON=""

  if is_localhost_host "${bind_host}" && [[ "${bind_port}" != "39333" ]]; then
    LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND="true"
    LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND_REASON="cached launch.env bind ${bind_host}:${bind_port:-unknown} looks like a temporary localhost test listener"
    return
  fi

  if is_localhost_host "${bind_host}" && is_localhost_host "${public_host}"; then
    LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND="true"
    LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND_REASON="cached launch.env endpoint stratum+tcp://${public_host:-unknown}:${bind_port:-unknown} looks like a temporary localhost test endpoint"
  fi
}

warn_if_suspicious_launch_env() {
  if [[ "${LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND}" == "true" ]]; then
    echo "warning: ${LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND_REASON}" >&2
    echo "warning: ignoring cached localhost bind/public endpoint unless you explicitly override PEPEPOW_POOL_CORE_STRATUM_BIND_HOST/PORT/HOST" >&2
  fi
}

load_launch_env_if_present() {
  local loaded_bind_host loaded_port loaded_public_host
  local loaded_share_difficulty loaded_job_interval loaded_snapshot_interval
  local loaded_estimated_hashrate_share_difficulty
  local loaded_template_mode loaded_template_fetch_interval
  local loaded_template_job_ttl loaded_template_job_cache_size
  local loaded_notify_debug_capture_limit
  local loaded_real_submitblock_enabled
  local loaded_real_submitblock_max_sends
  local loaded_rpc_host loaded_rpc_port loaded_rpc_url
  local loaded_rpc_user loaded_rpc_password loaded_rpc_timeout
  local loaded_version_source_order
  local loaded_low_diff_share_full_log_every_n
  local loaded_stratum_wire_difficulty_scale
  local loaded_vardiff_enabled loaded_vardiff_initial_difficulty
  local loaded_vardiff_min_difficulty loaded_vardiff_max_difficulty
  local loaded_vardiff_target_share_interval loaded_vardiff_retarget_interval
  local loaded_vardiff_min_shares loaded_vardiff_fast_share_interval
  local loaded_vardiff_slow_share_interval

  if [[ ! -f "${LAUNCH_ENV_FILE}" ]]; then
    return
  fi

  loaded_bind_host="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_BIND_HOST)"
  loaded_port="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_BIND_PORT)"
  loaded_public_host="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_HOST)"
  set_launch_env_suspicious_localhost_bind "${loaded_bind_host}" "${loaded_port}" "${loaded_public_host}"
  loaded_share_difficulty="$(launch_env_value PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY)"
  loaded_estimated_hashrate_share_difficulty="$(launch_env_value PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY)"
  loaded_job_interval="$(launch_env_value PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS)"
  loaded_snapshot_interval="$(launch_env_value PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS)"
  loaded_notify_debug_capture_limit="$(launch_env_value PEPEPOW_POOL_CORE_NOTIFY_DEBUG_CAPTURE_LIMIT)"
  loaded_template_mode="$(launch_env_value PEPEPOW_POOL_CORE_TEMPLATE_MODE)"
  loaded_template_fetch_interval="$(launch_env_value PEPEPOW_POOL_CORE_TEMPLATE_FETCH_INTERVAL_SECONDS)"
  loaded_template_job_ttl="$(launch_env_value PEPEPOW_POOL_CORE_TEMPLATE_JOB_TTL_SECONDS)"
  loaded_template_job_cache_size="$(launch_env_value PEPEPOW_POOL_CORE_TEMPLATE_JOB_CACHE_SIZE)"
  loaded_real_submitblock_enabled="$(launch_env_value PEPEPOW_ENABLE_REAL_SUBMITBLOCK)"
  loaded_real_submitblock_max_sends="$(launch_env_value PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS)"
  loaded_rpc_host="$(launch_env_value PEPEPOWD_RPC_HOST)"
  loaded_rpc_port="$(launch_env_value PEPEPOWD_RPC_PORT)"
  loaded_rpc_url="$(launch_env_value PEPEPOWD_RPC_URL)"
  loaded_rpc_user="$(launch_env_value PEPEPOWD_RPC_USER)"
  loaded_rpc_password="$(launch_env_value PEPEPOWD_RPC_PASSWORD)"
  loaded_rpc_timeout="$(launch_env_value PEPEPOWD_RPC_TIMEOUT_SECONDS)"
  loaded_version_source_order="$(launch_env_value PEPEPOW_HEADER_VERSION_SOURCE_ORDER_ENABLED)"
  loaded_low_diff_share_full_log_every_n="$(launch_env_value PEPEPOW_POOL_CORE_LOW_DIFF_SHARE_FULL_LOG_EVERY_N)"
  loaded_stratum_wire_difficulty_scale="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_WIRE_DIFFICULTY_SCALE)"
  loaded_vardiff_enabled="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_VARDIFF_ENABLED)"
  loaded_vardiff_initial_difficulty="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_VARDIFF_INITIAL_DIFFICULTY)"
  loaded_vardiff_min_difficulty="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_DIFFICULTY)"
  loaded_vardiff_max_difficulty="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MAX_DIFFICULTY)"
  loaded_vardiff_target_share_interval="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_VARDIFF_TARGET_SHARE_INTERVAL_SECONDS)"
  loaded_vardiff_retarget_interval="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_VARDIFF_RETARGET_INTERVAL_SECONDS)"
  loaded_vardiff_min_shares="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_SHARES)"
  loaded_vardiff_fast_share_interval="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_VARDIFF_FAST_SHARE_INTERVAL_SECONDS)"
  loaded_vardiff_slow_share_interval="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_VARDIFF_SLOW_SHARE_INTERVAL_SECONDS)"

  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_BIND_HOST+x}" && -n "${loaded_bind_host}" && "${LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND}" != "true" ]]; then
    BIND_HOST="${loaded_bind_host}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_BIND_PORT+x}" && -n "${loaded_port}" && "${LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND}" != "true" ]]; then
    PORT="${loaded_port}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_HOST+x}" && -n "${loaded_public_host}" && "${LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND}" != "true" ]]; then
    PUBLIC_HOST="${loaded_public_host}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY+x}" && -n "${loaded_share_difficulty}" ]]; then
    SHARE_DIFFICULTY="${loaded_share_difficulty}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY+x}" && -n "${loaded_estimated_hashrate_share_difficulty}" ]]; then
    ESTIMATED_HASHRATE_SHARE_DIFFICULTY="${loaded_estimated_hashrate_share_difficulty}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS+x}" && -n "${loaded_job_interval}" ]]; then
    JOB_INTERVAL_SECONDS="${loaded_job_interval}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS+x}" && -n "${loaded_snapshot_interval}" ]]; then
    SNAPSHOT_INTERVAL_SECONDS="${loaded_snapshot_interval}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_NOTIFY_DEBUG_CAPTURE_LIMIT+x}" && -n "${loaded_notify_debug_capture_limit}" ]]; then
    NOTIFY_DEBUG_CAPTURE_LIMIT="${loaded_notify_debug_capture_limit}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_TEMPLATE_MODE+x}" && -n "${loaded_template_mode}" ]]; then
    TEMPLATE_MODE="${loaded_template_mode}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_TEMPLATE_FETCH_INTERVAL_SECONDS+x}" && -n "${loaded_template_fetch_interval}" ]]; then
    TEMPLATE_FETCH_INTERVAL_SECONDS="${loaded_template_fetch_interval}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_TEMPLATE_JOB_TTL_SECONDS+x}" && -n "${loaded_template_job_ttl}" ]]; then
    TEMPLATE_JOB_TTL_SECONDS="${loaded_template_job_ttl}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_TEMPLATE_JOB_CACHE_SIZE+x}" && -n "${loaded_template_job_cache_size}" ]]; then
    TEMPLATE_JOB_CACHE_SIZE="${loaded_template_job_cache_size}"
  fi
  if [[ -z "${PEPEPOW_ENABLE_REAL_SUBMITBLOCK+x}" && -n "${loaded_real_submitblock_enabled}" ]]; then
    REAL_SUBMITBLOCK_ENABLED="${loaded_real_submitblock_enabled}"
  fi
  if [[ -z "${PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS+x}" && -n "${loaded_real_submitblock_max_sends}" ]]; then
    REAL_SUBMITBLOCK_MAX_SENDS="${loaded_real_submitblock_max_sends}"
  fi
  if [[ -z "${PEPEPOWD_RPC_HOST+x}" && -n "${loaded_rpc_host}" ]]; then
    RPC_HOST="${loaded_rpc_host}"
  fi
  if [[ -z "${PEPEPOWD_RPC_PORT+x}" && -n "${loaded_rpc_port}" ]]; then
    RPC_PORT="${loaded_rpc_port}"
  fi
  if [[ -z "${PEPEPOWD_RPC_URL+x}" && -n "${loaded_rpc_url}" ]]; then
    RPC_URL="${loaded_rpc_url}"
  fi
  if [[ -z "${PEPEPOWD_RPC_USER+x}" && -n "${loaded_rpc_user}" ]]; then
    RPC_USER="${loaded_rpc_user}"
  fi
  if [[ -z "${PEPEPOWD_RPC_PASSWORD+x}" && -n "${loaded_rpc_password}" ]]; then
    RPC_PASSWORD="${loaded_rpc_password}"
  fi
  if [[ -z "${PEPEPOWD_RPC_TIMEOUT_SECONDS+x}" && -n "${loaded_rpc_timeout}" ]]; then
    RPC_TIMEOUT_SECONDS="${loaded_rpc_timeout}"
  fi
  if [[ -z "${PEPEPOW_HEADER_VERSION_SOURCE_ORDER_ENABLED+x}" && -n "${loaded_version_source_order}" ]]; then
    VERSION_SOURCE_ORDER="${loaded_version_source_order}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_LOW_DIFF_SHARE_FULL_LOG_EVERY_N+x}" && -n "${loaded_low_diff_share_full_log_every_n}" ]]; then
    LOW_DIFF_SHARE_FULL_LOG_EVERY_N="${loaded_low_diff_share_full_log_every_n}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_WIRE_DIFFICULTY_SCALE+x}" && -n "${loaded_stratum_wire_difficulty_scale}" ]]; then
    STRATUM_WIRE_DIFFICULTY_SCALE="${loaded_stratum_wire_difficulty_scale}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_ENABLED+x}" && -n "${loaded_vardiff_enabled}" ]]; then
    VARDIFF_ENABLED="${loaded_vardiff_enabled}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_INITIAL_DIFFICULTY+x}" && -n "${loaded_vardiff_initial_difficulty}" ]]; then
    VARDIFF_INITIAL_DIFFICULTY="${loaded_vardiff_initial_difficulty}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_DIFFICULTY+x}" && -n "${loaded_vardiff_min_difficulty}" ]]; then
    VARDIFF_MIN_DIFFICULTY="${loaded_vardiff_min_difficulty}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MAX_DIFFICULTY+x}" && -n "${loaded_vardiff_max_difficulty}" ]]; then
    VARDIFF_MAX_DIFFICULTY="${loaded_vardiff_max_difficulty}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_TARGET_SHARE_INTERVAL_SECONDS+x}" && -n "${loaded_vardiff_target_share_interval}" ]]; then
    VARDIFF_TARGET_SHARE_INTERVAL_SECONDS="${loaded_vardiff_target_share_interval}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_RETARGET_INTERVAL_SECONDS+x}" && -n "${loaded_vardiff_retarget_interval}" ]]; then
    VARDIFF_RETARGET_INTERVAL_SECONDS="${loaded_vardiff_retarget_interval}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_SHARES+x}" && -n "${loaded_vardiff_min_shares}" ]]; then
    VARDIFF_MIN_SHARES="${loaded_vardiff_min_shares}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_FAST_SHARE_INTERVAL_SECONDS+x}" && -n "${loaded_vardiff_fast_share_interval}" ]]; then
    VARDIFF_FAST_SHARE_INTERVAL_SECONDS="${loaded_vardiff_fast_share_interval}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_VARDIFF_SLOW_SHARE_INTERVAL_SECONDS+x}" && -n "${loaded_vardiff_slow_share_interval}" ]]; then
    VARDIFF_SLOW_SHARE_INTERVAL_SECONDS="${loaded_vardiff_slow_share_interval}"
  fi
}

launch_env_value() {
  local var_name="$1"
  env -i bash -lc "source '${LAUNCH_ENV_FILE}' >/dev/null 2>&1; printf '%s' \"\${${var_name}:-}\""
}

masked_rpc_password() {
  if [[ -n "${RPC_PASSWORD}" ]]; then
    printf 'set'
    return
  fi
  printf 'unset'
}

print_paths() {
  cat <<EOF
endpoint: stratum+tcp://${PUBLIC_HOST}:${PORT}
bind: ${BIND_HOST}:${PORT}
hashrate_assumed_share_difficulty: ${SHARE_DIFFICULTY}
hashrate_assumed_share_difficulty_source: ${LAUNCH_ENV_FILE} -> PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY
stratum_wire_difficulty_scale: ${STRATUM_WIRE_DIFFICULTY_SCALE}
fixed_effective_share_difficulty: ${VARDIFF_INITIAL_DIFFICULTY}
fixed_effective_share_difficulty_source: ${LAUNCH_ENV_FILE} -> PEPEPOW_POOL_CORE_STRATUM_VARDIFF_INITIAL_DIFFICULTY
estimated_hashrate_difficulty: ${ESTIMATED_HASHRATE_SHARE_DIFFICULTY}
estimated_hashrate_difficulty_source: ${LAUNCH_ENV_FILE} -> PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY
notify_interval_seconds: ${JOB_INTERVAL_SECONDS}
notify_debug_capture_limit: ${NOTIFY_DEBUG_CAPTURE_LIMIT}
template_mode: ${TEMPLATE_MODE}
template_fetch_interval_seconds: ${TEMPLATE_FETCH_INTERVAL_SECONDS}
template_job_ttl_seconds: ${TEMPLATE_JOB_TTL_SECONDS}
template_job_cache_size: ${TEMPLATE_JOB_CACHE_SIZE}
enable_real_submitblock: ${REAL_SUBMITBLOCK_ENABLED}
real_submitblock_max_sends: ${REAL_SUBMITBLOCK_MAX_SENDS}
rpc_host: ${RPC_HOST}
rpc_port: ${RPC_PORT}
rpc_url: ${RPC_URL}
rpc_user: ${RPC_USER:-unset}
rpc_password: $(masked_rpc_password)
rpc_timeout_seconds: ${RPC_TIMEOUT_SECONDS}
stratum_notify_clean_jobs_legacy: ${CLEAN_JOBS_LEGACY}
pepepow_header_version_source_order_enabled: ${VERSION_SOURCE_ORDER}
stratum_vardiff_enabled: ${VARDIFF_ENABLED}
stratum_vardiff_initial_difficulty: ${VARDIFF_INITIAL_DIFFICULTY}
stratum_vardiff_min_difficulty: ${VARDIFF_MIN_DIFFICULTY}
stratum_vardiff_max_difficulty: ${VARDIFF_MAX_DIFFICULTY}
stratum_vardiff_target_share_interval_seconds: ${VARDIFF_TARGET_SHARE_INTERVAL_SECONDS}
stratum_vardiff_retarget_interval_seconds: ${VARDIFF_RETARGET_INTERVAL_SECONDS}
stratum_vardiff_min_shares: ${VARDIFF_MIN_SHARES}
stratum_vardiff_fast_share_interval_seconds: ${VARDIFF_FAST_SHARE_INTERVAL_SECONDS}
stratum_vardiff_slow_share_interval_seconds: ${VARDIFF_SLOW_SHARE_INTERVAL_SECONDS}
runtime_dir: ${RUNTIME_DIR}
pid_file: ${PID_FILE}
log_file: ${LOG_FILE}
share_log: ${SHARE_LOG}
candidate_event_log: ${CANDIDATE_EVENT_LOG}
candidate_outcome_event_log: ${CANDIDATE_OUTCOME_EVENT_LOG}
candidate_followup_event_log: ${FOLLOWUP_EVENT_LOG}
submit_evidence_log: ${SUBMIT_EVIDENCE_LOG}
notify_evidence_log: ${NOTIFY_EVIDENCE_LOG}
activity_snapshot: ${ACTIVITY_SNAPSHOT}
launch_env: ${LAUNCH_ENV_FILE}
EOF
  if [[ "${LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND}" == "true" ]]; then
    printf 'warning: %s\n' "${LAUNCH_ENV_SUSPICIOUS_LOCALHOST_BIND_REASON}"
  fi
}

is_process_alive() {
  local pid="$1"
  kill -0 "${pid}" 2>/dev/null
}

read_pid_file() {
  if [[ -f "${PID_FILE}" ]]; then
    tr -d '[:space:]' <"${PID_FILE}"
  fi
}

cmdline_for_pid() {
  local pid="$1"
  tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null || true
}

is_managed_stratum_pid() {
  local pid="$1"
  local cmdline
  cmdline="$(cmdline_for_pid "${pid}")"
  [[ "${cmdline}" == *"python3"* ]] && [[ "${cmdline}" == *"stratum_ingress.py"* ]]
}

remove_stale_pid_file_if_needed() {
  local pid
  pid="$(read_pid_file)"
  if [[ -z "${pid}" ]]; then
    return
  fi
  if ! is_process_alive "${pid}"; then
    rm -f "${PID_FILE}"
    return
  fi
  if ! is_managed_stratum_pid "${pid}"; then
    rm -f "${PID_FILE}"
  fi
}

listener_details() {
  ss -ltnp | grep -F ":${PORT} " || true
}

port_is_listening() {
  [[ -n "$(listener_details)" ]]
}

current_process_in_systemd_unit() {
  grep -Fq "/${SYSTEMD_UNIT_NAME}" "/proc/$$/cgroup" 2>/dev/null
}

systemd_unit_active() {
  command -v systemctl >/dev/null 2>&1 || return 1
  systemctl is-active --quiet "${SYSTEMD_UNIT_NAME}"
}

systemd_main_pid() {
  command -v systemctl >/dev/null 2>&1 || return 1
  systemctl show -p MainPID --value "${SYSTEMD_UNIT_NAME}" 2>/dev/null || true
}

systemd_owns_live_stratum() {
  local main_pid
  if ! systemd_unit_active; then
    return 1
  fi
  main_pid="$(systemd_main_pid)"
  if [[ -z "${main_pid}" || "${main_pid}" == "0" ]]; then
    return 1
  fi
  is_process_alive "${main_pid}" && is_managed_stratum_pid "${main_pid}"
}

guard_manual_service_mutation() {
  local action="${1:-control}"
  if current_process_in_systemd_unit; then
    return 0
  fi
  if ! systemd_owns_live_stratum; then
    return 0
  fi

  local main_pid
  main_pid="$(systemd_main_pid)"
  echo "refusing to ${action} live-stratum directly while ${SYSTEMD_UNIT_NAME} owns pid ${main_pid}" >&2
  echo "use: ${0} systemd-restart" >&2
  echo "or:  systemctl restart ${SYSTEMD_UNIT_NAME}" >&2
  return 1
}

rotate_log_if_needed() {
  if [[ ! -f "${LOG_FILE}" ]]; then
    return
  fi

  local current_size
  current_size="$(stat -c '%s' "${LOG_FILE}")"
  if (( current_size < LOG_ROTATE_BYTES )); then
    return
  fi

  mv "${LOG_FILE}" "${LOG_FILE}.1"
}

write_launch_env() {
  umask 077
  cat >"${LAUNCH_ENV_FILE}" <<EOF
PEPEPOW_POOL_CORE_STRATUM_BIND_HOST=${BIND_HOST}
PEPEPOW_POOL_CORE_STRATUM_BIND_PORT=${PORT}
PEPEPOW_POOL_CORE_STRATUM_PORT=${PORT}
PEPEPOW_POOL_CORE_STRATUM_HOST=${PUBLIC_HOST}
PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH=${SHARE_LOG}
PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_OUTPUT=${ACTIVITY_SNAPSHOT}
PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY=${SHARE_DIFFICULTY}
PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY=${ESTIMATED_HASHRATE_SHARE_DIFFICULTY}
PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS=${JOB_INTERVAL_SECONDS}
PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS=${SNAPSHOT_INTERVAL_SECONDS}
PEPEPOW_POOL_CORE_NOTIFY_DEBUG_CAPTURE_LIMIT=${NOTIFY_DEBUG_CAPTURE_LIMIT}
PEPEPOW_POOL_CORE_TEMPLATE_MODE=${TEMPLATE_MODE}
PEPEPOW_POOL_CORE_TEMPLATE_FETCH_INTERVAL_SECONDS=${TEMPLATE_FETCH_INTERVAL_SECONDS}
PEPEPOW_POOL_CORE_TEMPLATE_JOB_TTL_SECONDS=${TEMPLATE_JOB_TTL_SECONDS}
PEPEPOW_POOL_CORE_TEMPLATE_JOB_CACHE_SIZE=${TEMPLATE_JOB_CACHE_SIZE}
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=${REAL_SUBMITBLOCK_ENABLED}
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=${REAL_SUBMITBLOCK_MAX_SENDS}
PEPEPOWD_RPC_HOST=${RPC_HOST}
PEPEPOWD_RPC_PORT=${RPC_PORT}
PEPEPOWD_RPC_URL=${RPC_URL}
PEPEPOWD_RPC_USER=${RPC_USER}
PEPEPOWD_RPC_PASSWORD=${RPC_PASSWORD}
PEPEPOWD_RPC_TIMEOUT_SECONDS=${RPC_TIMEOUT_SECONDS}
PEPEPOW_STRATUM_NOTIFY_CLEAN_JOBS_LEGACY=${CLEAN_JOBS_LEGACY}
PEPEPOW_HEADER_VERSION_SOURCE_ORDER_ENABLED=${VERSION_SOURCE_ORDER}
PEPEPOW_POOL_CORE_LOW_DIFF_SHARE_FULL_LOG_EVERY_N=${LOW_DIFF_SHARE_FULL_LOG_EVERY_N}
PEPEPOW_POOL_CORE_STRATUM_WIRE_DIFFICULTY_SCALE=${STRATUM_WIRE_DIFFICULTY_SCALE}
PEPEPOW_POOL_CORE_STRATUM_VARDIFF_ENABLED=${VARDIFF_ENABLED}
PEPEPOW_POOL_CORE_STRATUM_VARDIFF_INITIAL_DIFFICULTY=${VARDIFF_INITIAL_DIFFICULTY}
PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_DIFFICULTY=${VARDIFF_MIN_DIFFICULTY}
PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MAX_DIFFICULTY=${VARDIFF_MAX_DIFFICULTY}
PEPEPOW_POOL_CORE_STRATUM_VARDIFF_TARGET_SHARE_INTERVAL_SECONDS=${VARDIFF_TARGET_SHARE_INTERVAL_SECONDS}
PEPEPOW_POOL_CORE_STRATUM_VARDIFF_RETARGET_INTERVAL_SECONDS=${VARDIFF_RETARGET_INTERVAL_SECONDS}
PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_SHARES=${VARDIFF_MIN_SHARES}
PEPEPOW_POOL_CORE_STRATUM_VARDIFF_FAST_SHARE_INTERVAL_SECONDS=${VARDIFF_FAST_SHARE_INTERVAL_SECONDS}
PEPEPOW_POOL_CORE_STRATUM_VARDIFF_SLOW_SHARE_INTERVAL_SECONDS=${VARDIFF_SLOW_SHARE_INTERVAL_SECONDS}
PYTHONUNBUFFERED=1
EOF
  chmod 600 "${LAUNCH_ENV_FILE}"
}

print_snapshot_summary() {
  if [[ ! -f "${ACTIVITY_SNAPSHOT}" ]]; then
    echo "snapshot: missing"
    return
  fi

  python3 - "${ACTIVITY_SNAPSHOT}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
meta = payload.get("meta", {})
pool = payload.get("pool", {})
miners = payload.get("miners", {})
accepted_total = 0
for miner_payload in miners.values():
    summary = miner_payload.get("summary", {})
    if isinstance(summary.get("acceptedShares"), int):
        accepted_total += summary["acceptedShares"]
print("snapshot: present")
print(f"last_share_at: {meta.get('lastShareAt')}")
print(f"sequence: {meta.get('sequence')}")
print(f"accepted_shares_total: {accepted_total}")
print(f"active_miners: {pool.get('activeMiners')}")
print(f"template_mode_effective: {meta.get('templateModeEffective')}")
print(f"template_fetch_status: {meta.get('templateFetchStatus')}")
print(f"template_daemon_rpc_status: {meta.get('templateDaemonRpcStatus')}")
print(f"template_latest_age_seconds: {meta.get('templateLatestTemplateAgeSeconds')}")
print(f"real_submit_enabled: {meta.get('realSubmitblockEnabled')}")
print(f"real_submit_send_budget: {meta.get('realSubmitblockSendBudget')}")
print(f"real_submit_send_budget_remaining: {meta.get('realSubmitblockSendBudgetRemaining')}")
print(f"real_submit_last_status: {meta.get('realSubmitblockLastStatus')}")
print(f"real_submit_attempt_count: {meta.get('realSubmitblockAttemptCount')}")
print(f"real_submit_sent_count: {meta.get('real_submit_sent_count')}")
print(f"real_submit_error_count: {meta.get('real_submit_error_count')}")
print(f"active_job_count: {meta.get('activeJobCount')}")

active_sessions = payload.get("activeSessions", {})
print(f"active_sessions_count: {len(active_sessions)}")
for sid, session in active_sessions.items():
    print(f"--- session:{sid} ---")
    print(f"  remote: {session.get('remoteAddress')}")
    print(f"  worker: {session.get('wallet')}.{session.get('worker')}")
    print(f"  submits: {session.get('submitsReceived')} (ok:{session.get('acceptedShares')} / rej:{session.get('rejectedShares')})")
    print(f"  effective_share_diff: {session.get('effectiveShareDifficulty')}")
    print(f"  miner_wire_diff: {session.get('minerWireDifficulty')}")
    print(f"  difficulty_scale: {session.get('difficultyScale')}")
    print(f"  legacy_notify: {session.get('cleanJobsLegacy')}")
    print(f"  last_share: {session.get('lastShareAt')}")
    if session.get("rejectReasonCounts"):
        rejections = ", ".join(f"{k}:{v}" for k, v in session["rejectReasonCounts"].items())
        print(f"  rejections: {rejections}")
PY
}

drill_status_service() {
  set_effective_defaults
  ensure_runtime_dir
  load_launch_env_if_present

  if [[ ! -f "${ACTIVITY_SNAPSHOT}" ]]; then
    echo "drill_status: snapshot_missing"
    return 1
  fi

  python3 - "${ACTIVITY_SNAPSHOT}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
meta = payload.get("meta", {})
template_fetch_status = meta.get("templateFetchStatus")
template_daemon_rpc_reachable = meta.get("templateDaemonRpcReachable")
real_submit_enabled = meta.get("realSubmitblockEnabled")
real_submit_attempt_count = meta.get("realSubmitblockAttemptCount")
real_submit_sent_count = meta.get("realSubmitblockSentCount")
real_submit_error_count = meta.get("realSubmitblockErrorCount")
print("drill_status: ready")
print(f"template_mode_effective: {meta.get('templateModeEffective')}")
print(f"template_fetch_status: {template_fetch_status}")
print(f"template_daemon_rpc_reachable: {template_daemon_rpc_reachable}")
print(f"real_submit_enabled: {real_submit_enabled}")
print(f"real_submit_send_budget: {meta.get('realSubmitblockSendBudget')}")
print(f"real_submit_send_budget_remaining: {meta.get('realSubmitblockSendBudgetRemaining')}")
print(f"real_submit_attempt_count: {real_submit_attempt_count}")
print(f"real_submit_sent_count: {real_submit_sent_count}")
print(f"real_submit_error_count: {real_submit_error_count}")
print(f"real_submit_last_status: {meta.get('realSubmitblockLastStatus')}")
print(f"real_submit_last_attempt_at: {meta.get('realSubmitblockLastAttemptAt')}")
print(f"real_submit_last_error: {meta.get('realSubmitblockLastError')}")

needs_hint = (
    real_submit_enabled is True
    or any((real_submit_attempt_count, real_submit_sent_count, real_submit_error_count))
    or template_fetch_status != "ok"
    or template_daemon_rpc_reachable is not True
)
if needs_hint:
    print("submit_safety_audit_hint: run './ops/scripts/live-stratum.sh submit-safety-audit'")
PY
}

submit_safety_audit_service() {
  set_effective_defaults
  ensure_runtime_dir
  load_launch_env_if_present

  local config_real_submit_enabled config_real_submit_max_sends
  local main_pid listener_line
  config_real_submit_enabled="$(launch_env_value PEPEPOW_ENABLE_REAL_SUBMITBLOCK)"
  config_real_submit_max_sends="$(launch_env_value PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS)"
  main_pid="$(systemd_main_pid)"
  listener_line="$(listener_details | head -n 1)"

  python3 - "${ACTIVITY_SNAPSHOT}" "${config_real_submit_enabled}" "${config_real_submit_max_sends}" "${main_pid}" "${listener_line}" <<'PY'
import json
import re
import sys
from pathlib import Path

snapshot_path = Path(sys.argv[1])
config_enabled_raw = sys.argv[2]
config_max_sends = sys.argv[3]
systemd_main_pid_raw = sys.argv[4]
listener_line = sys.argv[5]


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return None


def render_bool(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"


meta = {}
if snapshot_path.exists():
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    except Exception:
        meta = {}

process_enabled = normalize_bool(meta.get("realSubmitblockEnabled"))
config_enabled = normalize_bool(config_enabled_raw)
template_mode = meta.get("templateModeEffective")
template_fetch_status = meta.get("templateFetchStatus")
template_rpc_reachable = meta.get("templateDaemonRpcReachable")
attempt_count = meta.get("realSubmitblockAttemptCount")
sent_count = meta.get("realSubmitblockSentCount")
error_count = meta.get("realSubmitblockErrorCount")

systemd_main_pid = systemd_main_pid_raw.strip() or "unknown"
if systemd_main_pid == "0":
    systemd_main_pid = "unknown"

listener_pid = "unknown"
match = re.search(r'pid=(\d+)', listener_line)
if match:
    listener_pid = match.group(1)

if listener_pid == "unknown" or systemd_main_pid == "unknown":
    listener_owned_by_systemd = None
else:
    listener_owned_by_systemd = listener_pid == systemd_main_pid

if config_enabled is None or process_enabled is None:
    aligned = None
else:
    aligned = config_enabled == process_enabled

if process_enabled is True:
    safety_status = "warning-real-submit-enabled"
elif listener_owned_by_systemd is False:
    safety_status = "warning-listener-not-systemd-owned"
elif aligned is False:
    safety_status = "warning-runtime-config-mismatch"
elif (
    config_enabled is False
    and process_enabled is False
    and listener_owned_by_systemd is True
):
    safety_status = "ok-default-off"
else:
    safety_status = "unknown"

print("submit_safety_audit: ready")
print(f"config_real_submit_enabled={config_enabled_raw or 'unknown'}")
print(f"config_real_submit_max_sends={config_max_sends or 'unknown'}")
print(f"process_real_submit_enabled={render_bool(process_enabled)}")
print(f"process_real_submit_attempt_count={attempt_count}")
print(f"process_real_submit_sent_count={sent_count}")
print(f"process_real_submit_error_count={error_count}")
print(f"template_mode_effective={template_mode}")
print(f"template_fetch_status={template_fetch_status}")
print(f"template_daemon_rpc_reachable={template_rpc_reachable}")
print(f"systemd_main_pid={systemd_main_pid}")
print(f"stratum_listener_pid={listener_pid}")
print(f"listener_owned_by_systemd={render_bool(listener_owned_by_systemd)}")
print(f"real_submit_config_process_aligned={render_bool(aligned)}")
print(f"safety_status={safety_status}")
PY
}

print_runtime_sizes() {
  for path in "${LOG_FILE}" "${SHARE_LOG}" "${CANDIDATE_EVENT_LOG}" "${CANDIDATE_OUTCOME_EVENT_LOG}" "${FOLLOWUP_EVENT_LOG}" "${SUBMIT_EVIDENCE_LOG}" "${NOTIFY_EVIDENCE_LOG}" "${ACTIVITY_SNAPSHOT}"; do
    if [[ -f "${path}" ]]; then
      printf 'size_bytes[%s]: %s\n' "$(basename "${path}")" "$(stat -c '%s' "${path}")"
    fi
  done
}

candidate_events_service() {
  ensure_runtime_dir

  local count
  count="${2:-5}"
  if [[ ! "${count}" =~ ^[0-9]+$ ]]; then
    echo "candidate-events count must be an integer" >&2
    return 1
  fi
  if [[ ! -f "${CANDIDATE_EVENT_LOG}" ]]; then
    echo "candidate_events: none"
    return 0
  fi

  python3 - "${CANDIDATE_EVENT_LOG}" "${count}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
count = int(sys.argv[2])
lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
selected = lines[-count:]
print(f"candidate_events: {len(selected)}")
for raw_line in selected:
    payload = json.loads(raw_line)
    print("---")
    print(f"timestamp: {payload.get('timestamp')}")
    print(f"job_id: {payload.get('jobId')}")
    print(f"wallet: {payload.get('wallet')}")
    print(f"worker: {payload.get('worker')}")
    print(f"candidate_block_hash: {payload.get('candidateBlockHash')}")
    print(f"candidate_prep_status: {payload.get('candidatePrepStatus')}")
    print(f"dry_run_status: {payload.get('submitblockDryRunStatus')}")
    print(f"real_submit_enabled: {payload.get('realSubmitblockEnabled')}")
    print(f"submit_status: {payload.get('submitblockRealSubmitStatus')}")
    print(f"submit_attempted: {payload.get('submitblockAttempted')}")
    print(f"submit_sent: {payload.get('submitblockSent')}")
    print(f"submit_payload_hash: {payload.get('submitblockPayloadHash')}")
    print(f"submit_payload_bytes: {payload.get('submitblockPayloadBytes')}")
    print(f"submit_exception: {payload.get('submitblockException')}")
    print(f"followup_status: {payload.get('followupStatus')}")
    print(f"followup_checked_at: {payload.get('followupCheckedAt')}")
    print(f"followup_observed_height: {payload.get('followupObservedHeight')}")
    print(f"followup_observed_block_hash: {payload.get('followupObservedBlockHash')}")
    print(f"followup_note: {payload.get('followupNote')}")
PY
}

candidate_followup_service() {
  set_effective_defaults
  ensure_runtime_dir
  load_launch_env_if_present

  local count record
  count="5"
  record="false"
  shift || true
  for arg in "$@"; do
    if [[ "${arg}" == "--record" ]]; then
      record="true"
      continue
    fi
    if [[ "${arg}" =~ ^[0-9]+$ ]]; then
      count="${arg}"
      continue
    fi
    echo "candidate-followup accepts an optional count and --record" >&2
    return 1
  done
  if [[ ! -f "${CANDIDATE_EVENT_LOG}" ]]; then
    echo "candidate_followup: none"
    return 0
  fi

  python3 - "${POOL_CORE_DIR}" "${CANDIDATE_EVENT_LOG}" "${FOLLOWUP_EVENT_LOG}" "${CANDIDATE_OUTCOME_EVENT_LOG}" "${count}" "${record}" "${RPC_URL}" "${RPC_USER}" "${RPC_PASSWORD}" "${RPC_TIMEOUT_SECONDS}" <<'PY'
import json
import sys
from pathlib import Path

pool_core_dir = Path(sys.argv[1])
candidate_event_log = Path(sys.argv[2])
followup_event_log = Path(sys.argv[3])
outcome_event_log = Path(sys.argv[4])
count = int(sys.argv[5])
record = sys.argv[6].lower() == "true"
rpc_url = sys.argv[7]
rpc_user = sys.argv[8]
rpc_password = sys.argv[9]
rpc_timeout_seconds = float(sys.argv[10])

sys.path.insert(0, str(pool_core_dir))
from daemon_rpc import (  # noqa: E402
    DaemonRpcClient,
    append_candidate_followup_event,
    check_candidate_followup,
)

lines = [line for line in candidate_event_log.read_text(encoding="utf-8").splitlines() if line.strip()]
selected = lines[-count:]
rpc_client = DaemonRpcClient(
    rpc_url=rpc_url,
    rpc_user=rpc_user,
    rpc_password=rpc_password,
    timeout_seconds=rpc_timeout_seconds,
    cache_ttl_seconds=1,
)

print(f"candidate_followup: {len(selected)}")
for raw_line in selected:
    payload = json.loads(raw_line)
    followup = check_candidate_followup(
        payload.get("candidateBlockHash"),
        rpc_client=rpc_client,
    )
    if record:
        append_candidate_followup_event(
            followup_event_log,
            payload,
            followup,
            outcome_path=outcome_event_log,
        )
    print("---")
    print(f"timestamp: {payload.get('timestamp')}")
    print(f"job_id: {payload.get('jobId')}")
    print(f"candidate_block_hash: {payload.get('candidateBlockHash')}")
    print(f"followup_status: {followup.get('followupStatus')}")
    print(f"followup_checked_at: {followup.get('followupCheckedAt')}")
    print(f"followup_observed_height: {followup.get('followupObservedHeight')}")
    print(f"followup_observed_block_hash: {followup.get('followupObservedBlockHash')}")
    print(f"followup_note: {followup.get('followupNote')}")
print(f"followup_recorded: {record}")
PY
}

candidate_outcomes_service() {
  ensure_runtime_dir

  local count
  count="${2:-5}"
  if [[ ! "${count}" =~ ^[0-9]+$ ]]; then
    echo "candidate-outcomes count must be an integer" >&2
    return 1
  fi
  if [[ ! -f "${CANDIDATE_OUTCOME_EVENT_LOG}" ]]; then
    echo "candidate_outcomes: none"
    return 0
  fi

  python3 - "${CANDIDATE_OUTCOME_EVENT_LOG}" "${count}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
count = int(sys.argv[2])
lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
selected = lines[-count:]
print(f"candidate_outcomes: {len(selected)}")
for raw_line in selected:
    payload = json.loads(raw_line)
    print("---")
    print(f"timestamp: {payload.get('timestamp')}")
    print(f"candidate_timestamp: {payload.get('candidateTimestamp')}")
    print(f"job_id: {payload.get('jobId')}")
    print(f"candidate_block_hash: {payload.get('candidateBlockHash')}")
    print(f"candidate_outcome_status: {payload.get('candidateOutcomeStatus')}")
    print(f"submit_status: {payload.get('submitblockRealSubmitStatus')}")
    print(f"submit_attempted: {payload.get('submitblockAttempted')}")
    print(f"submit_sent: {payload.get('submitblockSent')}")
    print(f"submit_submitted_at: {payload.get('submitblockSubmittedAt')}")
    print(f"followup_status: {payload.get('followupStatus')}")
    print(f"followup_checked_at: {payload.get('followupCheckedAt')}")
    print(f"followup_observed_height: {payload.get('followupObservedHeight')}")
    print(f"followup_observed_block_hash: {payload.get('followupObservedBlockHash')}")
    print(f"followup_note: {payload.get('followupNote')}")
PY
}

candidate_followup_events_service() {
  ensure_runtime_dir

  local count
  count="${2:-5}"
  if [[ ! "${count}" =~ ^[0-9]+$ ]]; then
    echo "candidate-followup-events count must be an integer" >&2
    return 1
  fi
  if [[ ! -f "${FOLLOWUP_EVENT_LOG}" ]]; then
    echo "candidate_followup_events: none"
    return 0
  fi

  python3 - "${FOLLOWUP_EVENT_LOG}" "${count}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
count = int(sys.argv[2])
lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
selected = lines[-count:]
print(f"candidate_followup_events: {len(selected)}")
for raw_line in selected:
    payload = json.loads(raw_line)
    print("---")
    print(f"timestamp: {payload.get('timestamp')}")
    print(f"candidate_timestamp: {payload.get('candidateTimestamp')}")
    print(f"job_id: {payload.get('jobId')}")
    print(f"candidate_block_hash: {payload.get('candidateBlockHash')}")
    print(f"followup_status: {payload.get('followupStatus')}")
    print(f"followup_checked_at: {payload.get('followupCheckedAt')}")
    print(f"followup_observed_height: {payload.get('followupObservedHeight')}")
    print(f"followup_observed_block_hash: {payload.get('followupObservedBlockHash')}")
    print(f"followup_note: {payload.get('followupNote')}")
PY
}

candidate_probability_audit_service() {
  ensure_runtime_dir

  local count
  count="${2:-100000}"
  if [[ ! "${count}" =~ ^[0-9]+$ ]] || (( count == 0 )); then
    echo "candidate-probability-audit count must be a positive integer" >&2
    return 1
  fi
  if [[ ! -f "${SHARE_LOG}" ]]; then
    echo "candidate_probability_audit: none (share log not found)"
    return 0
  fi

  tail -n "${count}" "${SHARE_LOG}" | python3 "${SCRIPT_DIR}/candidate_probability_audit.py" "${count}" "${SHARE_LOG}"
}

share_target_variant_audit_service() {
  set_effective_defaults
  ensure_runtime_dir
  load_launch_env_if_present

  local count log_tail
  count="${2:-300}"
  if [[ ! "${count}" =~ ^[0-9]+$ ]] || (( count == 0 || count > 1000 )); then
    echo "share-target-variant-audit count must be an integer from 1 to 1000" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "share_target_variant_audit: none (submit evidence log not found)"
    return 0
  fi

  log_tail="$(tail -n 200 "${LOG_FILE}" 2>/dev/null || true)"
  tail -n "${count}" "${SUBMIT_EVIDENCE_LOG}" | PEPEPOW_STRATUM_LOG_TAIL="${log_tail}" python3 <(cat <<'PY'
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

count = int(sys.argv[1])
snapshot_path = Path(sys.argv[2])
launch_env_path = Path(sys.argv[3])

DIFF1_PEPEW = int("0000ffff00000000000000000000000000000000000000000000000000000000", 16)
DIFF1_BTC = int("00000000ffff000000000000000000000000000000000000000000000000000", 16)
MAX_TARGET = (1 << 256) - 1
SCALE_DEFAULT = 65536.0

def target_from(diff1, difficulty):
    if difficulty is None or not math.isfinite(difficulty) or difficulty <= 0:
        return None
    return max(1, min(MAX_TARGET, int(diff1 / difficulty)))

def fmt_target(value):
    return f"{value:064x}" if isinstance(value, int) else None

def as_float(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None

def launch_value(name):
    if not launch_env_path.exists():
        return None
    prefix = name + "="
    try:
        for raw_line in launch_env_path.read_text(encoding="utf-8").splitlines():
            if raw_line.startswith(prefix):
                return raw_line[len(prefix):].strip()
    except OSError:
        return None
    return None

def load_snapshot():
    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

rows = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        rows.append(json.loads(line))
    except Exception:
        continue

snapshot = load_snapshot()
meta = snapshot.get("meta", {}) if isinstance(snapshot, dict) else {}
sessions = snapshot.get("activeSessions", {}) if isinstance(snapshot, dict) else {}
active_session = next(iter(sessions.values()), {}) if isinstance(sessions, dict) and sessions else {}

effective = as_float(active_session.get("effectiveShareDifficulty"))
wire = as_float(active_session.get("minerWireDifficulty"))
scale = as_float(active_session.get("difficultyScale"))
if effective is None:
    for row in reversed(rows):
        effective = as_float(row.get("difficulty"))
        if effective is not None:
            break
if scale is None:
    scale = as_float(launch_value("PEPEPOW_POOL_CORE_STRATUM_WIRE_DIFFICULTY_SCALE")) or SCALE_DEFAULT
if wire is None and effective is not None:
    wire = effective * scale
assumed = as_float(meta.get("assumedShareDifficulty"))
vardiff_raw = launch_value("PEPEPOW_POOL_CORE_STRATUM_VARDIFF_ENABLED")
vardiff_enabled = (vardiff_raw or "").strip().lower() in {"1", "true", "yes", "on"}

latest_set_diff = None
for line in os.environ.get("PEPEPOW_STRATUM_LOG_TAIL", "").splitlines():
    if "mining.set_difficulty" not in line and "Difficulty sent:" not in line:
        continue
    match = re.search(r"minerWireDifficulty=([0-9.eE+-]+)", line)
    if match:
        latest_set_diff = match.group(1)
        continue
    match = re.search(r"difficulty=([0-9.eE+-]+)", line)
    if match:
        latest_set_diff = match.group(1)

current_target = target_from(DIFF1_PEPEW, effective)
btc_variant_target = target_from(DIFF1_BTC, effective)
missing_scale_target = target_from(DIFF1_PEPEW, effective * scale if effective is not None else None)
double_scale_target = target_from(DIFF1_PEPEW, effective / scale if effective is not None else None)

variants = {
    "current_pool_canonical": (current_target, "canonical"),
    "reversed_byte_current_target": (current_target, "reversed"),
    "pepew_diff1_canonical": (target_from(DIFF1_PEPEW, effective), "canonical"),
    "btc_diff1_canonical": (btc_variant_target, "canonical"),
    "effective_divided_by_65536": (double_scale_target, "canonical"),
    "effective_multiplied_by_65536": (missing_scale_target, "canonical"),
}

records = []
for row in rows:
    diag = row.get("shareHashDiagnostic")
    if not isinstance(diag, dict):
        diag = row
    hash_hex = diag.get("localComputedHash")
    if not isinstance(hash_hex, str) or len(hash_hex) != 64:
        continue
    try:
        canonical_int = int(hash_hex, 16)
        reversed_int = int(bytes.fromhex(hash_hex)[::-1].hex(), 16)
    except ValueError:
        continue
    records.append((row, diag, canonical_int, reversed_int))

counts = Counter()
for row, _diag, canonical_int, reversed_int in records:
    for name, (target, order) in variants.items():
        if target is None:
            continue
        value = reversed_int if order == "reversed" else canonical_int
        if value <= target:
            counts[name] += 1

print("share_target_variant_audit: ready")
print("sampleSource: submit-evidence-tail")
print(f"bounded_tail_requested: {count}")
print(f"bounded_tail_rows: {len(rows)}")
print(f"diagnostic_hash_rows: {len(records)}")
print("--- difficulty semantics ---")
print(f"effectiveShareDifficulty: {effective}")
print(f"minerWireDifficulty: {wire}")
print(f"difficultyScale: {scale}")
print(f"assumedShareDifficulty: {assumed}")
print(f"vardiffEnabled: {vardiff_enabled}")
print(f"latestMiningSetDifficultyTail: {latest_set_diff}")
print("--- share target variants ---")
print(f"currentPoolShareTargetUsed: {fmt_target(current_target)}")
print(f"pepewDiff1TargetAtEffective: {fmt_target(target_from(DIFF1_PEPEW, effective))}")
print(f"btcDiff1TargetAtEffective: {fmt_target(btc_variant_target)}")
print(f"targetIf65536ScaleMissing_effectiveTimesScale: {fmt_target(missing_scale_target)}")
print(f"targetIf65536ScaleDoubleApplied_effectiveDivScale: {fmt_target(double_scale_target)}")
print("--- sample status counts ---")
print(f"submitOutcomeCounts: {dict(Counter('accepted' if row.get('rejectReason') is None else 'rejected' for row in rows))}")
print(f"shareHashValidationCounts: {dict(Counter(row.get('shareHashValidationStatus') for row in rows))}")
print("--- acceptance-ratio diagnostic ---")
for name in variants:
    pct = (counts[name] / len(records) * 100.0) if records else 0.0
    print(f"{name}: {counts[name]}/{len(records)} ({pct:.2f}%)")
print("--- recent hash comparison variants ---")
for row, diag, canonical_int, reversed_int in records[-10:]:
    current = current_target or 0
    adjusted = double_scale_target or 0
    block_target_raw = diag.get("blockTargetUsed")
    if block_target_raw is None:
        block_target_raw = diag.get("blockTarget")
    try:
        block_target = int(block_target_raw, 16) if isinstance(block_target_raw, str) else None
    except ValueError:
        block_target = None
    print("---")
    print(f"timestamp: {row.get('timestamp')}")
    print(f"accepted: {row.get('rejectReason') is None}")
    print(f"reasonCode: {diag.get('reasonCode') or row.get('rejectReason') or 'pool-share'}")
    print(f"localComputedHash: {diag.get('localComputedHash')}")
    print(f"canonicalIntHex: {canonical_int:064x}")
    print(f"reversedIntHex: {reversed_int:064x}")
    print(f"meetsCurrentCanonical: {canonical_int <= current}")
    print(f"meetsCurrentReversed: {reversed_int <= current}")
    print(f"meets65536AdjustedCanonical: {canonical_int <= adjusted}")
    print(f"meets65536AdjustedReversed: {reversed_int <= adjusted}")
    print(f"blockTargetUsed: {block_target_raw}")
    print(f"meetsDaemonBlockTargetCanonical: {canonical_int <= block_target if block_target is not None else None}")
    print(f"meetsDaemonBlockTargetReversed: {reversed_int <= block_target if block_target is not None else None}")
PY
  ) "${count}" "${ACTIVITY_SNAPSHOT}" "${LAUNCH_ENV_FILE}"
}

preimage_reconstruction_audit_service() {
  ensure_runtime_dir

  local count log_tail
  count="${2:-300}"
  if [[ ! "${count}" =~ ^[0-9]+$ ]] || (( count == 0 || count > 1000 )); then
    echo "preimage-reconstruction-audit count must be an integer from 1 to 1000" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "preimage_reconstruction_audit: none (submit evidence log not found)"
    return 0
  fi

  log_tail="$(tail -n 200 "${LOG_FILE}" 2>/dev/null || true)"
  tail -n "${count}" "${SUBMIT_EVIDENCE_LOG}" | PEPEPOW_STRATUM_LOG_TAIL="${log_tail}" python3 <(cat <<'PY'
import json
import os
import re
import sys
from collections import Counter, defaultdict

count = int(sys.argv[1])

def load_rows():
    rows = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows

def tri_bool(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "missing"

def hex_equal(left, right):
    if not isinstance(left, str) or not isinstance(right, str) or not left or not right:
        return "missing"
    return "true" if left.lower() == right.lower() else "false"

def present(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True

def prefix_suffix(value, prefix=16, suffix=16):
    if not isinstance(value, str) or not value:
        return "missing"
    if len(value) <= prefix + suffix:
        return value
    return f"{value[:prefix]}..{value[-suffix:]}"

def compact_hash(value):
    if not isinstance(value, str) or not value:
        return "missing"
    return value[:16]

def ntime_as_int(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None

def parse_log_tail(raw_log):
    events = []
    notify_job_ids = []
    notify_counts = Counter()
    difficulty_count = 0
    wire_difficulty_count = 0
    last_difficulty_index = None
    notify_without_prior_difficulty = 0
    duplicated_notify_job_ids = []
    seen_jobs = set()

    for line in raw_log.splitlines():
        if "Difficulty sent:" in line or "method=mining.set_difficulty" in line:
            event_type = "difficulty"
            difficulty_count += 1
            if "method=mining.set_difficulty" in line:
                wire_difficulty_count += 1
            events.append((event_type, None, line))
            last_difficulty_index = len(events) - 1
            continue
        if "Notify sent:" in line:
            match = re.search(r"jobId=([^ ]+)", line)
            job_id = match.group(1) if match else None
            clean_match = re.search(r"cleanJobs=([^ ]+)", line)
            clean_jobs = clean_match.group(1) if clean_match else "missing"
            event_type = "notify"
            events.append((event_type, job_id, line))
            notify_counts[clean_jobs] += 1
            if job_id:
                notify_job_ids.append(job_id)
                if job_id in seen_jobs:
                    duplicated_notify_job_ids.append(job_id)
                seen_jobs.add(job_id)
            if last_difficulty_index is None:
                notify_without_prior_difficulty += 1

    notify_count = sum(notify_counts.values())
    latest_notify_order = notify_job_ids[-8:]
    every_notify_after_difficulty = notify_count > 0 and notify_without_prior_difficulty == 0
    return {
        "notify_count": notify_count,
        "clean_notify_counts": dict(notify_counts),
        "difficulty_count": difficulty_count,
        "wire_difficulty_count": wire_difficulty_count,
        "notify_without_prior_difficulty": notify_without_prior_difficulty,
        "every_notify_has_prior_difficulty_in_tail": every_notify_after_difficulty,
        "latest_notify_job_ids": latest_notify_order,
        "duplicated_notify_job_ids": duplicated_notify_job_ids[-8:],
        "notify_params_mutation_check": "not-available-in-current-log-tail",
    }

rows = load_rows()

issued_vs_submit = Counter(tri_bool(row.get("issuedVsSubmitReconstructionMatch")) for row in rows)
header_match = Counter(hex_equal(row.get("header80Hex"), row.get("independentAuthoritativeHeader80Hex")) for row in rows)
hash_match = Counter(hex_equal(row.get("localComputedHash"), row.get("independentAuthoritativeShareHash")) for row in rows)
job_status = Counter(row.get("jobStatus") or "missing" for row in rows)
target_status = Counter(row.get("targetValidationStatus") or "missing" for row in rows)
share_hash_status = Counter(row.get("shareHashValidationStatus") or "missing" for row in rows)
reject_reasons = Counter(row.get("rejectReason") or "accepted" for row in rows)

field_names = [
    "issuedJobCoinb1",
    "issuedJobCoinb2",
    "coinbaseLocalHex",
    "coinbaseHashLocal",
    "issuedJobMerkleBranch",
    "merkleRoot",
    "preimagePrevhash",
    "preimageNbits",
    "ntime",
    "preimageJobNtime",
    "preimageVersion",
    "header80Hex",
    "independentAuthoritativeHeader80Hex",
    "localComputedHash",
    "independentAuthoritativeShareHash",
]
field_presence = {
    name: dict(Counter("present" if present(row.get(name)) else "missing" for row in rows))
    for name in field_names
}

jobs = defaultdict(list)
for row in rows:
    jobs[row.get("jobId") or "missing"].append(row)

job_summaries = []
for job_id, job_rows in jobs.items():
    extranonce2_values = [row.get("extranonce2") for row in job_rows if isinstance(row.get("extranonce2"), str)]
    ntime_values = [row.get("ntime") for row in job_rows if isinstance(row.get("ntime"), str)]
    job_ntime_values = [row.get("preimageJobNtime") for row in job_rows if isinstance(row.get("preimageJobNtime"), str)]
    nonce_values = [row.get("nonce") for row in job_rows if isinstance(row.get("nonce"), str)]
    ntime_ints = [ntime_as_int(value) for value in ntime_values]
    ntime_ints = [value for value in ntime_ints if value is not None]
    expected_ex2_hex_len = 8
    ex2_size_match = Counter(
        "true" if isinstance(value, str) and len(value) == expected_ex2_hex_len else "false"
        for value in extranonce2_values
    )
    job_ntime_set = set(job_ntime_values)
    ntime_differs = any(
        isinstance(row.get("ntime"), str)
        and isinstance(row.get("preimageJobNtime"), str)
        and row.get("ntime").lower() != row.get("preimageJobNtime").lower()
        for row in job_rows
    )
    job_summaries.append(
        {
            "jobId": job_id,
            "rows": len(job_rows),
            "jobStatusCounts": dict(Counter(row.get("jobStatus") or "missing" for row in job_rows)),
            "uniqueExtranonce2": len(set(extranonce2_values)),
            "extranonce2SizeMatches8Hex": dict(ex2_size_match),
            "ntimeMin": f"{min(ntime_ints):08x}" if ntime_ints else "missing",
            "ntimeMax": f"{max(ntime_ints):08x}" if ntime_ints else "missing",
            "jobNtimeValues": sorted(job_ntime_set)[-3:] if job_ntime_set else ["missing"],
            "ntimeDiffersFromJobNtime": ntime_differs,
            "uniqueNonces": len(set(nonce_values)),
        }
    )
job_summaries.sort(key=lambda item: (-item["rows"], item["jobId"]))

def contrast_rows(predicate, limit=5):
    return [row for row in rows if predicate(row)][:limit]

accepted_rows = contrast_rows(lambda row: row.get("rejectReason") is None)
rejected_rows = contrast_rows(lambda row: row.get("rejectReason") == "low-difficulty-share")

def print_contrast(label, selected):
    print(label)
    if not selected:
        print("  none")
        return
    for row in selected:
        print("---")
        print(f"timestamp: {row.get('timestamp')}")
        print(f"jobId: {row.get('jobId')}")
        print(f"jobStatus: {row.get('jobStatus')}")
        print(f"extranonce2: {row.get('extranonce2')}")
        print(f"ntime: {row.get('ntime')}")
        print(f"nonce: {row.get('nonce')}")
        print(f"header80: {prefix_suffix(row.get('header80Hex'))}")
        print(f"independentHeader80: {prefix_suffix(row.get('independentAuthoritativeHeader80Hex'))}")
        print(f"localHashPrefix: {compact_hash(row.get('localComputedHash'))}")
        print(f"authoritativeHashPrefix: {compact_hash(row.get('independentAuthoritativeShareHash'))}")
        print(f"issuedVsSubmitReconstructionMatch: {row.get('issuedVsSubmitReconstructionMatch')}")
        print(f"header80MatchesIndependent: {hex_equal(row.get('header80Hex'), row.get('independentAuthoritativeHeader80Hex'))}")
        print(f"hashMatchesIndependent: {hex_equal(row.get('localComputedHash'), row.get('independentAuthoritativeShareHash'))}")
        print(f"shareTargetPrefix: {compact_hash(row.get('shareTarget'))}")
        print(f"blockTargetPrefix: {compact_hash(row.get('blockTarget'))}")

log_summary = parse_log_tail(os.environ.get("PEPEPOW_STRATUM_LOG_TAIL", ""))

if issued_vs_submit.get("false", 0) or header_match.get("false", 0):
    likely_class = "B. submit-time reconstruction differs from issued notify"
elif hash_match.get("false", 0):
    likely_class = "F. ntime or nonce endian/placement mismatch"
elif header_match.get("true", 0) == len(rows) and hash_match.get("true", 0) == len(rows):
    likely_class = "C. independent authoritative path is matching local path, so both may share the same wrong preimage"
elif job_status.get("previous", 0) > len(rows) * 0.2:
    likely_class = "D. clean-job / previous-job window mismatch"
else:
    missing_critical = [
        name
        for name in ("issuedJobCoinb1", "issuedJobCoinb2", "issuedJobMerkleBranch", "header80Hex", "independentAuthoritativeHeader80Hex")
        if field_presence.get(name, {}).get("missing", 0)
    ]
    likely_class = (
        "H. insufficient evidence; missing " + ", ".join(missing_critical[:3])
        if missing_critical
        else "C. independent authoritative path is matching local path, so both may share the same wrong preimage"
    )

print("preimage_reconstruction_audit: ready")
print(f"bounded_tail_requested: {count}")
print(f"bounded_tail_rows: {len(rows)}")
print("--- reconstruction alignment counters ---")
print(f"issuedVsSubmitReconstructionMatch: {dict(issued_vs_submit)}")
print(f"header80EqualsIndependentAuthoritativeHeader80: {dict(header_match)}")
print(f"localComputedHashEqualsIndependentAuthoritativeShareHash: {dict(hash_match)}")
print(f"jobStatusCounts: {dict(job_status)}")
print(f"targetValidationStatusCounts: {dict(target_status)}")
print(f"shareHashValidationStatusCounts: {dict(share_hash_status)}")
print(f"rejectReasonCounts: {dict(reject_reasons)}")
print("--- submit field stability by job ---")
for item in job_summaries[:10]:
    print(
        f"jobId={item['jobId']} rows={item['rows']} statuses={item['jobStatusCounts']} "
        f"uniqueExtranonce2={item['uniqueExtranonce2']} ex2Size8Hex={item['extranonce2SizeMatches8Hex']} "
        f"ntimeMin={item['ntimeMin']} ntimeMax={item['ntimeMax']} jobNtimeValues={item['jobNtimeValues']} "
        f"ntimeDiffersFromJobNtime={item['ntimeDiffersFromJobNtime']} uniqueNonces={item['uniqueNonces']}"
    )
print("--- notify / difficulty ordering from stratum.log tail ---")
for key, value in log_summary.items():
    print(f"{key}: {value}")
print("--- reconstruction field presence ---")
for name in field_names:
    print(f"{name}: {field_presence[name]}")
print("--- accepted contrast rows ---")
print_contrast("accepted", accepted_rows)
print("--- low-difficulty contrast rows ---")
print_contrast("low-difficulty-share", rejected_rows)
print("--- likely mismatch class ---")
print(likely_class)
PY
  ) "${count}"
}

notify_submit_payload_audit_service() {
  ensure_runtime_dir

  local count
  count="${2:-300}"
  if [[ ! "${count}" =~ ^[0-9]+$ ]] || (( count == 0 || count > 1000 )); then
    echo "notify-submit-payload-audit count must be an integer from 1 to 1000" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "notify_submit_payload_audit: none (submit evidence log not found)"
    return 0
  fi

  python3 <(cat <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

count = int(sys.argv[1])
notify_path = Path(sys.argv[2])
submit_path = Path(sys.argv[3])

def read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    except OSError:
        return []
    return rows

def eq_state(left, right):
    if left is None or right is None:
        return "missing"
    if isinstance(left, str) and isinstance(right, str):
        return "match" if left.lower() == right.lower() else "mismatch"
    return "match" if left == right else "mismatch"

def matched(row):
    value = row.get("notifyEvidenceMatched")
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "missing"

def digest_match(row):
    value = row.get("notifyVsSubmitJobCacheDigestMatch")
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "missing"

def prefix(value, chars=16):
    if not isinstance(value, str) or not value:
        return "missing"
    return value[:chars]

notify_rows = read_jsonl(notify_path)
submit_rows = read_jsonl(submit_path)
notify_by_key = {}
for row in notify_rows:
    key = (row.get("sessionId"), row.get("jobId"))
    if key[0] and key[1]:
        notify_by_key[key] = row

field_pairs = {
    "prevhash": ("notifyPrevhashSent", "submitPrevhashUsed", "prevhashSent", "preimagePrevhash"),
    "version": ("notifyVersionSent", "submitVersionUsed", "versionSent", "preimageVersion"),
    "nbits": ("notifyNbitsSent", "submitNbitsUsed", "nbitsSent", "preimageNbits"),
    "ntime": ("notifyNtimeSent", "submitNtimeUsed", "ntimeSent", "preimageJobNtime"),
    "coinbase1": ("notifyCoinbase1Sha256", "submitCoinbase1Sha256", "coinbase1Sha256", None),
    "coinbase2": ("notifyCoinbase2Sha256", "submitCoinbase2Sha256", "coinbase2Sha256", None),
    "merkleBranch": ("notifyMerkleBranchDigest", "submitMerkleBranchDigest", "merkleBranchDigest", None),
    "extranonce1": ("notifyExtranonce1", "submitExtranonce1", "extranonce1", "extranonce1"),
    "extranonce2Size": ("notifyExtranonce2Size", "submitExtranonce2Size", "extranonce2Size", None),
}

per_field = {name: Counter() for name in field_pairs}
examples = []
contrast = Counter()
submits_with_tail_notify = 0
for row in submit_rows:
    key = (row.get("sessionId"), row.get("jobId"))
    notify = notify_by_key.get(key)
    if notify is not None:
        submits_with_tail_notify += 1
    outcome = "accepted" if row.get("rejectReason") is None else row.get("rejectReason")
    any_mismatch = False
    for name, (notify_field, submit_field, notify_fallback, submit_fallback) in field_pairs.items():
        left = row.get(notify_field)
        right = row.get(submit_field)
        if left is None and notify is not None:
            left = notify.get(notify_fallback)
        if right is None and submit_fallback is not None:
            right = row.get(submit_fallback)
        state = eq_state(left, right)
        per_field[name][state] += 1
        if state == "mismatch":
            any_mismatch = True
    contrast[(outcome, "mismatch" if any_mismatch else "no-mismatch")] += 1
    if any_mismatch and len(examples) < 5:
        examples.append((row, notify))

jobs_with_notify = {row.get("jobId") for row in notify_rows if row.get("jobId")}
submit_jobs = {row.get("jobId") for row in submit_rows if row.get("jobId")}

print("notify_submit_payload_audit: ready")
print(f"bounded_tail_requested: {count}")
print(f"notifyRows: {len(notify_rows)}")
print(f"submitRows: {len(submit_rows)}")
print(f"jobsWithNotifyEvidence: {len(jobs_with_notify)}")
print(f"submitJobs: {len(submit_jobs)}")
print(f"submitJobsWithNotifyEvidenceInTail: {len(jobs_with_notify & submit_jobs)}")
print(f"submitsWithMatchingNotifyEvidenceField: {dict(Counter(matched(row) for row in submit_rows))}")
print(f"submitsWithNotifyEvidenceInTail: {submits_with_tail_notify}")
print(f"notifyVsSubmitJobCacheDigestMatch: {dict(Counter(digest_match(row) for row in submit_rows))}")
print("--- per-field comparison counts ---")
for name in field_pairs:
    print(f"{name}: {dict(per_field[name])}")
print("--- accepted vs low-difficulty contrast by mismatch status ---")
for key, value in sorted(contrast.items()):
    print(f"{key[0]}:{key[1]}={value}")
print("--- latest mismatch examples ---")
if not examples:
    print("none")
else:
    for row, notify in examples:
        print("---")
        print(f"timestamp: {row.get('timestamp')}")
        print(f"jobId: {row.get('jobId')}")
        print(f"jobStatus: {row.get('jobStatus')}")
        print(f"rejectReason: {row.get('rejectReason') or 'accepted'}")
        print(f"notifyEvidenceMatched: {row.get('notifyEvidenceMatched')}")
        print(f"notifyEvidenceDigest: {prefix(row.get('notifyEvidenceDigest') or (notify or {}).get('notifyEvidenceDigest'))}")
        print(f"submitJobCacheDigest: {prefix(row.get('submitJobCacheDigest'))}")
        for name, (notify_field, submit_field, notify_fallback, submit_fallback) in field_pairs.items():
            left = row.get(notify_field)
            right = row.get(submit_field)
            if left is None and notify is not None:
                left = notify.get(notify_fallback)
            if right is None and submit_fallback is not None:
                right = row.get(submit_fallback)
            state = eq_state(left, right)
            if state == "mismatch":
                print(f"{name}: notify={prefix(str(left), 24)} submit={prefix(str(right), 24)}")
PY
  ) "${count}" <(tail -n "${count}" "${NOTIFY_EVIDENCE_LOG}" 2>/dev/null || true) <(tail -n "${count}" "${SUBMIT_EVIDENCE_LOG}" 2>/dev/null || true)
}

header_convention_audit_service() {
  ensure_runtime_dir

  local count
  count="${2:-100}"
  if [[ ! "${count}" =~ ^[0-9]+$ ]] || (( count == 0 || count > 1000 )); then
    echo "header-convention-audit count must be an integer from 1 to 1000" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "header_convention_audit: none (submit evidence log not found)"
    return 0
  fi

  python3 <(cat <<'PY'
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

count = int(sys.argv[1])
pool_core_dir = Path(sys.argv[2])
notify_path = Path(sys.argv[3])
submit_path = Path(sys.argv[4])
sys.path.insert(0, str(pool_core_dir))

from pepepow_pow import blake3_hash, hoohash_v110

VARIANT_NAMES = (
    "current_pool",
    "notify_wire_header",
    "block_header_internal",
    "merkle_reversed_only",
    "nonce_reversed_only",
    "ntime_nonce_reversed",
    "hoohash_input_reversed_header80",
)

def read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    except OSError:
        return []
    return rows

def hx(value, length=None):
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if not value:
        return None
    if length is not None and len(value) != length:
        return None
    try:
        bytes.fromhex(value)
    except ValueError:
        return None
    return value

def bytes_from_hex(value, length=None):
    value = hx(value, length)
    if value is None:
        return None
    return bytes.fromhex(value)

def reverse_hex_bytes(value, length=None):
    raw = bytes_from_hex(value, length)
    if raw is None:
        return None
    return raw[::-1]

def double_sha256(payload):
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()

def hoohash_header80(header):
    if not isinstance(header, (bytes, bytearray)) or len(header) != 80:
        return None
    header = bytes(header)
    masked_header = header[:76] + (b"\x00" * 4)
    header_hash = blake3_hash(header)
    matrix_seed = blake3_hash(masked_header)
    nonce = int.from_bytes(header[76:80], byteorder="little", signed=False)
    return hoohash_v110(matrix_seed, header_hash, nonce)[::-1].hex()

def apply_merkle_current(coinbase_hash, branches):
    root = coinbase_hash
    for sibling_hash in branches:
        sibling = bytes_from_hex(sibling_hash, 64)
        if sibling is None:
            return None
        root = double_sha256(root + sibling[::-1])
    return root

def apply_merkle_wire(coinbase_hash, branches):
    root = coinbase_hash
    for sibling_hash in branches:
        sibling = bytes_from_hex(sibling_hash, 64)
        if sibling is None:
            return None
        root = double_sha256(root + sibling)
    return root

def branches_for(row):
    value = row.get("issuedJobMerkleBranch")
    if isinstance(value, list):
        return value
    return []

def coinbase_hash_for(row):
    coinb1 = hx(row.get("issuedJobCoinb1"))
    coinb2 = hx(row.get("issuedJobCoinb2"))
    extranonce1 = hx(row.get("extranonce1"))
    extranonce2 = hx(row.get("extranonce2"))
    if None in (coinb1, coinb2, extranonce1, extranonce2):
        return None
    return double_sha256(bytes.fromhex(coinb1 + extranonce1 + extranonce2 + coinb2))

def merkle_current_for(row):
    logged = bytes_from_hex(row.get("merkleRoot"), 64)
    if logged is not None:
        return logged
    coinbase_hash = coinbase_hash_for(row)
    if coinbase_hash is None:
        return None
    return apply_merkle_current(coinbase_hash, branches_for(row))

def merkle_wire_for(row):
    coinbase_hash = coinbase_hash_for(row)
    if coinbase_hash is None:
        return None
    return apply_merkle_wire(coinbase_hash, branches_for(row))

def assemble(*parts):
    if any(part is None for part in parts):
        return None
    header = b"".join(parts)
    return header if len(header) == 80 else None

def build_headers(row):
    current = bytes_from_hex(row.get("header80Hex"), 160)
    version_wire = bytes_from_hex(row.get("notifyVersionSent") or row.get("submitVersionUsed") or row.get("preimageVersion"), 8)
    prevhash_wire = bytes_from_hex(row.get("notifyPrevhashSent") or row.get("submitPrevhashUsed"), 64)
    nbits_wire = bytes_from_hex(row.get("notifyNbitsSent") or row.get("submitNbitsUsed") or row.get("preimageNbits"), 8)
    ntime_wire = bytes_from_hex(row.get("submitNtimeUsed") or row.get("notifyNtimeSent") or row.get("ntime"), 8)
    nonce_wire = bytes_from_hex(row.get("nonce"), 8)
    merkle_current = merkle_current_for(row)
    merkle_wire = merkle_wire_for(row)
    prevhash_internal = reverse_hex_bytes(row.get("preimagePrevhash"), 64) or prevhash_wire

    headers = {
        "current_pool": current,
        "notify_wire_header": assemble(
            version_wire,
            prevhash_wire,
            merkle_wire,
            ntime_wire,
            nbits_wire,
            nonce_wire,
        ),
        "block_header_internal": assemble(
            version_wire[::-1] if version_wire is not None else None,
            prevhash_internal,
            merkle_current,
            ntime_wire[::-1] if ntime_wire is not None else None,
            nbits_wire[::-1] if nbits_wire is not None else None,
            nonce_wire[::-1] if nonce_wire is not None else None,
        ),
        "merkle_reversed_only": (
            current[:36] + current[36:68][::-1] + current[68:] if current is not None else None
        ),
        "nonce_reversed_only": (
            current[:76] + current[76:80][::-1] if current is not None else None
        ),
        "ntime_nonce_reversed": (
            current[:68] + current[68:72][::-1] + current[72:76] + current[76:80][::-1]
            if current is not None else None
        ),
        "hoohash_input_reversed_header80": current[::-1] if current is not None else None,
    }
    return headers

def prefix_suffix(value, chars=16):
    if isinstance(value, bytes):
        value = value.hex()
    if not isinstance(value, str) or not value:
        return "missing"
    if len(value) <= chars * 2:
        return value
    return f"{value[:chars]}..{value[-chars:]}"

def short(value, chars=16):
    if not isinstance(value, str) or not value:
        return "missing"
    return value[:chars]

def is_accepted(row):
    return row.get("rejectReason") is None

def is_lowdiff(row):
    return row.get("rejectReason") == "low-difficulty-share"

def pass_state(hash_hex, target_hex):
    target = hx(target_hex, 64)
    if hash_hex is None or target is None:
        return None
    try:
        return int(hash_hex, 16) <= int(target, 16)
    except ValueError:
        return None

def classify_variant(name, stats, current_stats):
    total = stats["hash_rows"]
    if total == 0:
        return "no-data"
    ratio = stats["pass"] / total
    if ratio >= 0.90:
        return "near all-pass"
    lowdiff_total = stats["lowdiff_total"]
    lowdiff_ratio = stats["lowdiff_pass"] / lowdiff_total if lowdiff_total else 0.0
    accepted_floor = 1 if stats["accepted_total"] else 0
    if (
        name != "current_pool"
        and lowdiff_ratio >= 0.50
        and stats["accepted_pass"] >= accepted_floor
    ):
        return "plausibly miner-like"
    return "near random"

notify_rows = read_jsonl(notify_path)
submit_rows = read_jsonl(submit_path)
notify_by_key = {
    (row.get("sessionId"), row.get("jobId")): row
    for row in notify_rows
    if row.get("sessionId") and row.get("jobId")
}

records = []
for row in submit_rows:
    notify = notify_by_key.get((row.get("sessionId"), row.get("jobId")))
    if notify is not None:
        for key, notify_key in (
            ("notifyVersionSent", "versionSent"),
            ("notifyPrevhashSent", "prevhashSent"),
            ("notifyNbitsSent", "nbitsSent"),
            ("notifyNtimeSent", "ntimeSent"),
        ):
            row.setdefault(key, notify.get(notify_key))
    headers = build_headers(row)
    hashes = {name: hoohash_header80(header) for name, header in headers.items()}
    target = row.get("shareTarget")
    passes = {name: pass_state(hash_hex, target) for name, hash_hex in hashes.items()}
    if any(value is not None for value in passes.values()):
        records.append((row, headers, hashes, passes))

stats = {
    name: Counter(
        {
            "total": len(records),
            "hash_rows": 0,
            "pass": 0,
            "accepted_total": 0,
            "accepted_pass": 0,
            "lowdiff_total": 0,
            "lowdiff_pass": 0,
        }
    )
    for name in VARIANT_NAMES
}
examples = {name: [] for name in VARIANT_NAMES}
for row, _headers, hashes, passes in records:
    for name in VARIANT_NAMES:
        if hashes.get(name) is not None:
            stats[name]["hash_rows"] += 1
        if is_accepted(row):
            stats[name]["accepted_total"] += 1
        if is_lowdiff(row):
            stats[name]["lowdiff_total"] += 1
        if passes.get(name) is True:
            stats[name]["pass"] += 1
            if is_accepted(row):
                stats[name]["accepted_pass"] += 1
            if is_lowdiff(row):
                stats[name]["lowdiff_pass"] += 1
                if name != "current_pool" and len(examples[name]) < 3:
                    examples[name].append(row)

current_stats = stats["current_pool"]
ranked = sorted(
    (name for name in VARIANT_NAMES if name != "current_pool"),
    key=lambda name: (
        stats[name]["lowdiff_pass"] - current_stats["lowdiff_pass"],
        stats[name]["pass"],
    ),
    reverse=True,
)
best = None
for name in ranked:
    if classify_variant(name, stats[name], current_stats) == "plausibly miner-like":
        best = name
        break
contrast_variant = best or (ranked[0] if ranked else "notify_wire_header")

print("header_convention_audit: ready")
print(f"bounded_tail_requested: {count}")
print(f"notifyRows: {len(notify_rows)}")
print(f"submitRows: {len(submit_rows)}")
print(f"hashableRows: {len(records)}")
print("--- variants ---")
for name in VARIANT_NAMES:
    item = stats[name]
    denom = item["hash_rows"]
    ratio = (item["pass"] / denom * 100.0) if denom else 0.0
    print(f"{name}:")
    print(f"  pass: {item['pass']}/{denom}")
    print(f"  acceptedRowsPass: {item['accepted_pass']}/{item['accepted_total']}")
    print(f"  lowDifficultyRejectedRowsPass: {item['lowdiff_pass']}/{item['lowdiff_total']}")
    print(f"  passRatio: {ratio:.2f}%")
    print(f"  interpretation: {classify_variant(name, item, current_stats)}")
    if name != "current_pool":
        print("  firstRejectedRowsThatWouldPass:")
        if not examples[name]:
            print("    none")
        for row in examples[name]:
            print(
                "    "
                f"jobId={row.get('jobId')} extranonce2={row.get('extranonce2')} "
                f"ntime={row.get('ntime')} nonce={row.get('nonce')}"
            )
print("--- best variant ---")
print(f"bestVariant: {best or 'none'}")
if best is None:
    print("bestVariantReason: no single bounded variant produced a miner-like pass profile")
else:
    gain = stats[best]["lowdiff_pass"] - current_stats["lowdiff_pass"]
    print(f"bestVariantReason: lowDifficultyRejectedRowsPassGain={gain}")

accepted_rows = [record for record in records if is_accepted(record[0])][:3]
rejected_rows = [record for record in records if is_lowdiff(record[0])][:3]
print("--- compact row contrast ---")
print(f"contrastVariant: {contrast_variant}")
for label, selected in (("accepted", accepted_rows), ("low-difficulty-rejected", rejected_rows)):
    if not selected:
        print(f"{label}: none")
        continue
    for row, headers, hashes, _passes in selected:
        current_header = headers.get("current_pool")
        variant_header = headers.get(contrast_variant)
        print("---")
        print(f"rowType: {label}")
        print(f"jobId: {row.get('jobId')}")
        print(f"extranonce2: {row.get('extranonce2')}")
        print(f"ntime: {row.get('ntime')}")
        print(f"nonce: {row.get('nonce')}")
        print(f"currentHeader80: {prefix_suffix(current_header)}")
        print(f"variantHeader80: {prefix_suffix(variant_header)}")
        print(f"currentHashPrefix: {short(hashes.get('current_pool'))}")
        print(f"variantHashPrefix: {short(hashes.get(contrast_variant))}")
        print(f"shareTargetPrefix: {short(row.get('shareTarget'))}")
PY
  ) "${count}" "${POOL_CORE_DIR}" <(tail -n "${count}" "${NOTIFY_EVIDENCE_LOG}" 2>/dev/null || true) <(tail -n "${count}" "${SUBMIT_EVIDENCE_LOG}" 2>/dev/null || true)
}

latest_reject_service() {
  ensure_runtime_dir

  local tail_count
  tail_count=200

  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "latest_reject: none (log not found)"
    return 0
  fi

  python3 - "${tail_count}" <(tail -n "${tail_count}" -- "${SUBMIT_EVIDENCE_LOG}" 2>/dev/null || true) <<'PY'
import json
import sys
from pathlib import Path

tail_count = int(sys.argv[1])
path = Path(sys.argv[2])
try:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
except Exception as exc:
    print(f"latest_reject: error reading log: {exc}")
    sys.exit(0)

reject_record = None
for line in reversed(lines):
    try:
        rec = json.loads(line)
        if rec.get("rejectReason") is not None:
            reject_record = rec
            break
    except Exception:
        continue

if reject_record is None:
    print(f"latest_reject: none (no rejected daemon-template submissions found in last {tail_count} entries)")
    sys.exit(0)

r = reject_record
print("latest_reject: found")
print(f"timestamp:             {r.get('timestamp')}")
print(f"remote:                {r.get('remoteAddress')}")
print(f"wallet:                {r.get('wallet')}")
print(f"worker:                {r.get('worker')}")
print(f"job_id:                {r.get('jobId')}")
print(f"job_status:            {r.get('jobStatus')}")
print(f"reject_reason:         {r.get('rejectReason')}")
print(f"reject_detail:         {r.get('rejectDetail')}")
print(f"clean_jobs_legacy:     {r.get('cleanJobsLegacy')}")
print(f"hash_validation_mode:  {r.get('shareHashValidationMode')}")
print("--- submit fields ---")
print(f"extranonce1:           {r.get('extranonce1')}")
print(f"extranonce2:           {r.get('extranonce2')}")
print(f"ntime:                 {r.get('ntime')}")
print(f"nonce:                 {r.get('nonce')}")
print("--- preimage source ---")
print(f"preimage_version:      {r.get('preimageVersion')}")
print(f"preimage_prevhash:     {r.get('preimagePrevhash')}")
print(f"preimage_nbits:        {r.get('preimageNbits')}")
print(f"preimage_job_ntime:    {r.get('preimageJobNtime')}")
print("--- hashing ---")
print(f"header80:              {r.get('header80Hex')}")
print(f"computed_hash:         {r.get('localComputedHash')}")
print(f"share_target:          {r.get('shareTarget')}")
print(f"meets_share_target:    {r.get('meetsShareTarget')}")
print(f"refined_reason_code:   {r.get('refinedReasonCode')}")
print("--- bounded variant comparison ---")
variants = r.get("variantTargetMatches")
if isinstance(variants, dict):
    for vname, vresult in variants.items():
        print(f"  variant[{vname}]: {'PASS' if vresult is True else ('FAIL' if vresult is False else 'ERR')}")
else:
    print("  variants: not available (preimage may have failed earlier)")
PY
}

submit_evidence_service() {
  ensure_runtime_dir

  local count
  count="${2:-5}"
  if [[ ! "${count}" =~ ^[0-9]+$ ]]; then
    echo "submit-evidence count must be an integer" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "submit_evidence: none"
    return 0
  fi

  python3 - "${count}" <(tail -n "${count}" -- "${SUBMIT_EVIDENCE_LOG}") <<'PY'
import json
import sys
from pathlib import Path

count = int(sys.argv[1])
tail_path = Path(sys.argv[2])
try:
    lines = [line.rstrip("\n") for line in tail_path.read_text(encoding="utf-8").splitlines() if line.strip()]
except Exception as exc:
    print(f"submit_evidence: error_reading_log: {exc}")
    sys.exit(0)

if not lines:
    print("submit_evidence: empty")
    sys.exit(0)

selected = lines[-count:]
print(f"latest_evidence_entries: {len(selected)}")
preferred_keys = [
    "timestamp",
    "jobId",
    "wallet",
    "worker",
    "candidateBlockHash",
    "candidatePrepStatus",
    "submitblockDryRunStatus",
    "realSubmitblockEnabled",
    "submitblockRealSubmitStatus",
    "submitblockAttempted",
    "submitblockSent",
    "submitblockSubmittedAt",
    "submitblockDaemonResult",
    "submitblockDaemonError",
    "submitblockDaemonAcceptedLikely",
    "submitblockDaemonBestBlockHash",
    "submitblockException",
]
large_hex_keys = {"coinbaseLocalHex", "header80Hex"}

for raw_line in selected:
    try:
        payload = json.loads(raw_line)
    except Exception:
        continue
    print("---")
    printed_keys = set()
    for key in preferred_keys:
        if key in payload:
            print(f"{key}: {payload.get(key)}")
            printed_keys.add(key)
    for k, v in payload.items():
        if k in printed_keys:
            continue
        if k in large_hex_keys and isinstance(v, str) and len(v) > 128:
            print(f"{k}: {v[:64]}...{v[-64:]} ({len(v)//2} bytes)")
        else:
            print(f"{k}: {v}")
PY
}

submit_evidence_find_service() {
  ensure_runtime_dir

  local candidate_hash tail_lines
  candidate_hash="${2:-}"
  tail_lines="${3:-5000}"
  if [[ -z "${candidate_hash}" ]]; then
    echo "usage: $0 submit-evidence-find <candidate_hash> [tail_lines]" >&2
    return 1
  fi
  if [[ ! "${tail_lines}" =~ ^[0-9]+$ ]] || [[ "${tail_lines}" -lt 1 ]]; then
    echo "submit-evidence-find tail_lines must be a positive integer" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "submit_evidence_find: none (submit evidence log not found)"
    return 0
  fi

  tail -n "${tail_lines}" -- "${SUBMIT_EVIDENCE_LOG}" \
    | python3 -c '
import json
import sys

candidate_hash = sys.argv[1].strip().lower()
tail_lines = int(sys.argv[2])
preferred_keys = [
    "timestamp",
    "jobId",
    "worker",
    "wallet",
    "candidateBlockHash",
    "localComputedHash",
    "candidatePossible",
    "meetsBlockTarget",
    "shareHashValidationStatus",
    "targetValidationStatus",
    "submitblockAttempted",
    "submitblockSent",
    "submitblockRealSubmitStatus",
    "submitblockSubmittedAt",
    "submitblockDaemonResult",
    "submitblockDaemonError",
    "submitblockDaemonAcceptedLikely",
    "submitblockDaemonBestBlockHash",
    "submitblockException",
    "realSubmitblockEnabled",
]
hash_match_keys = [
    "candidateBlockHash",
    "blockHash",
    "submitblockCandidateHash",
    "submitblockPayloadHash",
    "shareHash",
    "localComputedHash",
    "independentAuthoritativeShareHash",
]

def value_or_null(payload, key):
    return payload.get(key, None)

matches = []
for raw_line in sys.stdin:
    raw_line = raw_line.strip()
    if not raw_line:
        continue
    try:
        payload = json.loads(raw_line)
    except Exception:
        continue
    found_match = False
    for key in hash_match_keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip().lower() == candidate_hash:
            found_match = True
            break
    if not found_match:
        continue
    matches.append(payload)

if not matches:
    print(
        "submit_evidence_find: no match found for "
        f"{candidate_hash} in last {tail_lines} lines"
    )
    sys.exit(0)

print(f"submit_evidence_find: {len(matches)} match(es)")
print(f"candidate_hash: {candidate_hash}")
print(f"bounded_tail_lines: {tail_lines}")
for payload in matches:
    print("---")
    for key in preferred_keys:
        print(f"{key}: {value_or_null(payload, key)}")
    print(
        "matchedHashField: "
        f"{next((key for key in hash_match_keys if isinstance(payload.get(key), str) and payload.get(key).strip().lower() == candidate_hash), None)}"
    )
' "${candidate_hash}" "${tail_lines}"
}

candidate_freshness_audit_service() {
  ensure_runtime_dir

  local tail_lines helper_path tmpdir candidate_tail_path submit_tail_path followup_tail_path outcome_tail_path
  tail_lines="${2:-200}"
  helper_path="${SCRIPT_DIR}/candidate_freshness_audit.py"
  if [[ ! "${tail_lines}" =~ ^[0-9]+$ ]] || [[ "${tail_lines}" -lt 1 ]]; then
    echo "candidate-freshness-audit tail_lines must be a positive integer" >&2
    return 1
  fi
  if [[ ! -f "${CANDIDATE_EVENT_LOG}" ]]; then
    echo "candidate_freshness_audit: none (candidate events log not found)"
    return 0
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "candidate_freshness_audit: none (submit evidence log not found)"
    return 0
  fi

  tmpdir="$(mktemp -d)"
  trap 'rm -rf "'"${tmpdir}"'"' RETURN
  candidate_tail_path="${tmpdir}/candidate-events.tail.jsonl"
  submit_tail_path="${tmpdir}/submit-evidence.tail.jsonl"
  followup_tail_path="-"
  outcome_tail_path="-"
  tail -n "${tail_lines}" -- "${CANDIDATE_EVENT_LOG}" > "${candidate_tail_path}"
  tail -n "${tail_lines}" -- "${SUBMIT_EVIDENCE_LOG}" > "${submit_tail_path}"
  if [[ -f "${FOLLOWUP_EVENT_LOG}" ]]; then
    followup_tail_path="${tmpdir}/candidate-followup-events.tail.jsonl"
    tail -n "${tail_lines}" -- "${FOLLOWUP_EVENT_LOG}" > "${followup_tail_path}"
  elif [[ -f "${CANDIDATE_OUTCOME_EVENT_LOG}" ]]; then
    outcome_tail_path="${tmpdir}/candidate-outcome-events.tail.jsonl"
    tail -n "${tail_lines}" -- "${CANDIDATE_OUTCOME_EVENT_LOG}" > "${outcome_tail_path}"
  fi

  python3 "${helper_path}" "${tail_lines}" \
    "${candidate_tail_path}" \
    "${submit_tail_path}" \
    "${ACTIVITY_SNAPSHOT}" \
    "${followup_tail_path}" \
    "${outcome_tail_path}"
}

replay_evidence_service() {
  ensure_runtime_dir
  local count
  count="${2:-1}"
  if [[ ! "${count}" =~ ^[0-9]+$ ]]; then
    echo "replay-evidence count must be an integer" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "replay-evidence: error: ${SUBMIT_EVIDENCE_LOG} not found" >&2
    return 1
  fi

  python3 "${POOL_CORE_DIR}/tools/replay_submit_evidence.py" "${SUBMIT_EVIDENCE_LOG}" --latest "${count}"
}

miner_hash_correlation_service() {
  ensure_runtime_dir

  local miner_log count
  miner_log="${2:-}"
  count="${3:-300}"
  if [[ -z "${miner_log}" ]]; then
    echo "miner-hash-correlation requires a hoo_gpu -P log path" >&2
    return 1
  fi
  if [[ ! -f "${miner_log}" ]]; then
    echo "miner-hash-correlation: miner log not found: ${miner_log}" >&2
    return 1
  fi
  if [[ ! "${count}" =~ ^[0-9]+$ ]] || [[ "${count}" -lt 1 ]] || [[ "${count}" -gt 1000 ]]; then
    echo "miner-hash-correlation tail-lines must be an integer from 1 to 1000" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "miner-hash-correlation: submit evidence log not found: ${SUBMIT_EVIDENCE_LOG}" >&2
    return 1
  fi

  tail -n "${count}" "${SUBMIT_EVIDENCE_LOG}" | python3 "${SCRIPT_DIR}/miner_hash_correlation.py" "${miner_log}" "${count}"
}

single_submit_preimage_trace_service() {
  ensure_runtime_dir

  local miner_log count
  miner_log="${2:-}"
  count="${3:-300}"
  shift 3 || true
  if [[ -z "${miner_log}" ]]; then
    echo "single-submit-preimage-trace requires a hoo_gpu -P log path" >&2
    return 1
  fi
  if [[ ! -f "${miner_log}" ]]; then
    echo "single-submit-preimage-trace: miner log not found: ${miner_log}" >&2
    return 1
  fi
  if [[ ! "${count}" =~ ^[0-9]+$ ]] || [[ "${count}" -lt 1 ]] || [[ "${count}" -gt 1000 ]]; then
    echo "single-submit-preimage-trace tail-lines must be an integer from 1 to 1000" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "single-submit-preimage-trace: submit evidence log not found: ${SUBMIT_EVIDENCE_LOG}" >&2
    return 1
  fi
  if [[ ! -f "${NOTIFY_EVIDENCE_LOG}" ]]; then
    echo "single-submit-preimage-trace: notify evidence log not found: ${NOTIFY_EVIDENCE_LOG}" >&2
    return 1
  fi

  python3 "${SCRIPT_DIR}/single_submit_preimage_trace.py" \
    "${miner_log}" \
    "${count}" \
    <(tail -n "${count}" "${SUBMIT_EVIDENCE_LOG}") \
    <(tail -n "${count}" "${NOTIFY_EVIDENCE_LOG}") \
    "${POOL_CORE_DIR}" \
    "$@"
}

nomp_parity_audit_service() {
  ensure_runtime_dir

  local miner_log count
  miner_log="${2:-}"
  count="${3:-300}"
  if [[ -z "${miner_log}" ]]; then
    echo "nomp-parity-audit requires a hoo_gpu -P log path" >&2
    return 1
  fi
  if [[ ! -f "${miner_log}" ]]; then
    echo "nomp-parity-audit: miner log not found: ${miner_log}" >&2
    return 1
  fi
  if [[ ! "${count}" =~ ^[0-9]+$ ]] || [[ "${count}" -lt 1 ]] || [[ "${count}" -gt 1000 ]]; then
    echo "nomp-parity-audit tail-lines must be an integer from 1 to 1000" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "nomp-parity-audit: submit evidence log not found: ${SUBMIT_EVIDENCE_LOG}" >&2
    return 1
  fi
  if [[ ! -f "${NOTIFY_EVIDENCE_LOG}" ]]; then
    echo "nomp-parity-audit: notify evidence log not found: ${NOTIFY_EVIDENCE_LOG}" >&2
    return 1
  fi

  python3 "${SCRIPT_DIR}/nomp_parity_audit.py" \
    "${miner_log}" \
    "${count}" \
    <(tail -n "${count}" "${SUBMIT_EVIDENCE_LOG}") \
    <(tail -n "${count}" "${NOTIFY_EVIDENCE_LOG}") \
    "${POOL_CORE_DIR}"
}

js_nomp_oracle_service() {
  ensure_runtime_dir

  local miner_log count nomp_root node_bin
  miner_log="${2:-}"
  count="${3:-300}"
  nomp_root="${REPO_ROOT}/.runtime/reference/nomp-pepepow-debug"
  if [[ -z "${miner_log}" ]]; then
    echo "js-nomp-oracle requires a hoo_gpu -P log path" >&2
    return 1
  fi
  if [[ ! -f "${miner_log}" ]]; then
    echo "js-nomp-oracle: miner log not found: ${miner_log}" >&2
    return 1
  fi
  if [[ ! "${count}" =~ ^[0-9]+$ ]] || [[ "${count}" -lt 1 ]] || [[ "${count}" -gt 1000 ]]; then
    echo "js-nomp-oracle tail-lines must be an integer from 1 to 1000" >&2
    return 1
  fi
  if [[ ! -f "${SUBMIT_EVIDENCE_LOG}" ]]; then
    echo "js-nomp-oracle: submit evidence log not found: ${SUBMIT_EVIDENCE_LOG}" >&2
    return 1
  fi
  if [[ ! -f "${NOTIFY_EVIDENCE_LOG}" ]]; then
    echo "js-nomp-oracle: notify evidence log not found: ${NOTIFY_EVIDENCE_LOG}" >&2
    return 1
  fi
  if [[ ! -d "${nomp_root}" ]]; then
    echo "js-nomp-oracle: NOMP reference tree not found: ${nomp_root}" >&2
    return 1
  fi
  if ! node_bin="$(detect_node_bin)"; then
    echo "js-nomp-oracle: no node runtime found on host" >&2
    return 1
  fi

  "${node_bin}" "${SCRIPT_DIR}/js_nomp_oracle.js" \
    "${miner_log}" \
    "${count}" \
    <(tail -n "${count}" "${SUBMIT_EVIDENCE_LOG}") \
    <(tail -n "${count}" "${NOTIFY_EVIDENCE_LOG}") \
    "${nomp_root}"
}

start_service() {
  set_effective_defaults
  ensure_runtime_dir
  load_launch_env_if_present
  warn_if_suspicious_launch_env
  remove_stale_pid_file_if_needed

  local pid
  pid="$(read_pid_file)"
  if [[ -n "${pid}" ]] && is_process_alive "${pid}" && is_managed_stratum_pid "${pid}"; then
    echo "live-stratum already running with pid ${pid}"
    print_paths
    return 0
  fi

  if port_is_listening; then
    echo "port ${PORT} is already occupied by another process" >&2
    listener_details >&2
    return 1
  fi

  write_launch_env
  rotate_log_if_needed
  touch "${LOG_FILE}"
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "live-stratum start requested" >>"${LOG_FILE}"

  (
    cd "${POOL_CORE_DIR}"
    export PYTHONUNBUFFERED=1
    export PEPEPOW_POOL_CORE_STRATUM_BIND_HOST="${BIND_HOST}"
    export PEPEPOW_POOL_CORE_STRATUM_BIND_PORT="${PORT}"
    export PEPEPOW_POOL_CORE_STRATUM_PORT="${PORT}"
    export PEPEPOW_POOL_CORE_STRATUM_HOST="${PUBLIC_HOST}"
    export PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH="${SHARE_LOG}"
    export PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_OUTPUT="${ACTIVITY_SNAPSHOT}"
    export PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY="${SHARE_DIFFICULTY}"
    export PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY="${ESTIMATED_HASHRATE_SHARE_DIFFICULTY}"
    export PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS="${JOB_INTERVAL_SECONDS}"
    export PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS="${SNAPSHOT_INTERVAL_SECONDS}"
    export PEPEPOW_POOL_CORE_NOTIFY_DEBUG_CAPTURE_LIMIT="${NOTIFY_DEBUG_CAPTURE_LIMIT}"
    export PEPEPOW_POOL_CORE_TEMPLATE_MODE="${TEMPLATE_MODE}"
    export PEPEPOW_POOL_CORE_TEMPLATE_FETCH_INTERVAL_SECONDS="${TEMPLATE_FETCH_INTERVAL_SECONDS}"
    export PEPEPOW_POOL_CORE_TEMPLATE_JOB_TTL_SECONDS="${TEMPLATE_JOB_TTL_SECONDS}"
    export PEPEPOW_POOL_CORE_TEMPLATE_JOB_CACHE_SIZE="${TEMPLATE_JOB_CACHE_SIZE}"
    export PEPEPOW_ENABLE_REAL_SUBMITBLOCK="${REAL_SUBMITBLOCK_ENABLED}"
    export PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS="${REAL_SUBMITBLOCK_MAX_SENDS}"
    export PEPEPOWD_RPC_HOST="${RPC_HOST}"
    export PEPEPOWD_RPC_PORT="${RPC_PORT}"
    export PEPEPOWD_RPC_URL="${RPC_URL}"
    export PEPEPOWD_RPC_USER="${RPC_USER}"
    export PEPEPOWD_RPC_PASSWORD="${RPC_PASSWORD}"
    export PEPEPOWD_RPC_TIMEOUT_SECONDS="${RPC_TIMEOUT_SECONDS}"
    export PEPEPOW_STRATUM_NOTIFY_CLEAN_JOBS_LEGACY="${CLEAN_JOBS_LEGACY}"
    export PEPEPOW_HEADER_VERSION_SOURCE_ORDER_ENABLED="${VERSION_SOURCE_ORDER}"
    export PEPEPOW_POOL_CORE_LOW_DIFF_SHARE_FULL_LOG_EVERY_N="${LOW_DIFF_SHARE_FULL_LOG_EVERY_N}"
    export PEPEPOW_POOL_CORE_STRATUM_VARDIFF_ENABLED="${VARDIFF_ENABLED}"
    export PEPEPOW_POOL_CORE_STRATUM_VARDIFF_INITIAL_DIFFICULTY="${VARDIFF_INITIAL_DIFFICULTY}"
    export PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_DIFFICULTY="${VARDIFF_MIN_DIFFICULTY}"
    export PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MAX_DIFFICULTY="${VARDIFF_MAX_DIFFICULTY}"
    export PEPEPOW_POOL_CORE_STRATUM_VARDIFF_TARGET_SHARE_INTERVAL_SECONDS="${VARDIFF_TARGET_SHARE_INTERVAL_SECONDS}"
    export PEPEPOW_POOL_CORE_STRATUM_VARDIFF_RETARGET_INTERVAL_SECONDS="${VARDIFF_RETARGET_INTERVAL_SECONDS}"
    export PEPEPOW_POOL_CORE_STRATUM_VARDIFF_MIN_SHARES="${VARDIFF_MIN_SHARES}"
    export PEPEPOW_POOL_CORE_STRATUM_VARDIFF_FAST_SHARE_INTERVAL_SECONDS="${VARDIFF_FAST_SHARE_INTERVAL_SECONDS}"
    export PEPEPOW_POOL_CORE_STRATUM_VARDIFF_SLOW_SHARE_INTERVAL_SECONDS="${VARDIFF_SLOW_SHARE_INTERVAL_SECONDS}"
    setsid python3 stratum_ingress.py </dev/null >>"${LOG_FILE}" 2>&1 &
    echo "$!" >"${PID_FILE}"
  )

  pid="$(read_pid_file)"
  for _attempt in $(seq 1 50); do
    if [[ -n "${pid}" ]] && ! is_process_alive "${pid}"; then
      echo "live-stratum failed to stay running" >&2
      tail -n 50 "${LOG_FILE}" >&2 || true
      rm -f "${PID_FILE}"
      return 1
    fi
    if port_is_listening; then
      echo "live-stratum started with pid ${pid}"
      print_paths
      return 0
    fi
    sleep 0.1
  done

  echo "live-stratum did not bind ${BIND_HOST}:${PORT} within 5 seconds" >&2
  tail -n 50 "${LOG_FILE}" >&2 || true
  if [[ -n "${pid}" ]] && is_process_alive "${pid}"; then
    kill "${pid}" 2>/dev/null || true
  fi
  rm -f "${PID_FILE}"
  return 1
}

stop_service() {
  set_effective_defaults
  ensure_runtime_dir
  load_launch_env_if_present
  remove_stale_pid_file_if_needed
  guard_manual_service_mutation "stop"

  local pid
  pid="$(read_pid_file)"
  if [[ -z "${pid}" ]]; then
    echo "live-stratum is not running"
    return 0
  fi

  if ! is_process_alive "${pid}"; then
    rm -f "${PID_FILE}"
    echo "removed stale pid file"
    return 0
  fi

  echo "stopping live-stratum pid ${pid}"
  kill "${pid}" 2>/dev/null || true
  for _attempt in $(seq 1 100); do
    if ! is_process_alive "${pid}"; then
      rm -f "${PID_FILE}"
      echo "live-stratum stopped"
      return 0
    fi
    sleep 0.1
  done

  echo "pid ${pid} did not exit after SIGTERM; sending SIGKILL"
  kill -9 "${pid}" 2>/dev/null || true
  for _attempt in $(seq 1 20); do
    if ! is_process_alive "${pid}"; then
      rm -f "${PID_FILE}"
      echo "live-stratum stopped"
      return 0
    fi
    sleep 0.1
  done

  echo "unable to stop pid ${pid}" >&2
  return 1
}

status_service() {
  set_effective_defaults
  ensure_runtime_dir
  load_launch_env_if_present
  warn_if_suspicious_launch_env

  local pid status
  pid="$(read_pid_file)"
  status="stopped"
  if [[ -n "${pid}" ]] && is_process_alive "${pid}" && is_managed_stratum_pid "${pid}"; then
    status="running"
  fi

  echo "status: ${status}"
  echo "pid: ${pid:-none}"
  echo "listener:"
  if port_is_listening; then
    listener_details
  else
    echo "not listening on ${PORT}"
  fi
  print_snapshot_summary
  print_runtime_sizes
  print_paths
}

logs_service() {
  ensure_runtime_dir
  touch "${LOG_FILE}"
  tail -n 100 -f "${LOG_FILE}"
}

restart_service() {
  set_effective_defaults
  ensure_runtime_dir
  load_launch_env_if_present
  warn_if_suspicious_launch_env
  guard_manual_service_mutation "restart"
  stop_service
  set_effective_defaults
  start_service
}

systemd_restart_service() {
  set_effective_defaults
  ensure_runtime_dir
  load_launch_env_if_present
  warn_if_suspicious_launch_env
  write_launch_env

  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl is not available; wrote ${LAUNCH_ENV_FILE} only" >&2
    return 1
  fi

  echo "prepared ${LAUNCH_ENV_FILE} for ${SYSTEMD_UNIT_NAME}"
  if ! systemctl restart "${SYSTEMD_UNIT_NAME}"; then
    echo "failed to restart ${SYSTEMD_UNIT_NAME}; launch env is prepared for the next operator-approved restart" >&2
    return 1
  fi

  systemctl status "${SYSTEMD_UNIT_NAME}" --no-pager --lines=15 || true
}

case "${SUBCOMMAND}" in
  start)
    start_service
    ;;
  stop)
    stop_service
    ;;
  restart)
    restart_service
    ;;
  systemd-restart)
    systemd_restart_service
    ;;
  status)
    status_service
    ;;
  drill-status)
    drill_status_service
    ;;
  submit-safety-audit)
    submit_safety_audit_service
    ;;
  candidate-events)
    candidate_events_service "$@"
    ;;
  candidate-followup)
    candidate_followup_service "$@"
    ;;
  candidate-outcomes)
    candidate_outcomes_service "$@"
    ;;
  candidate-followup-events)
    candidate_followup_events_service "$@"
    ;;
  candidate-probability-audit)
    candidate_probability_audit_service "$@"
    ;;
  share-target-variant-audit)
    share_target_variant_audit_service "$@"
    ;;
  preimage-reconstruction-audit)
    preimage_reconstruction_audit_service "$@"
    ;;
  notify-submit-payload-audit)
    notify_submit_payload_audit_service "$@"
    ;;
  header-convention-audit)
    header_convention_audit_service "$@"
    ;;
  latest-reject)
    latest_reject_service
    ;;
  submit-evidence)
    submit_evidence_service "$@"
    ;;
  submit-evidence-find)
    submit_evidence_find_service "$@"
    ;;
  candidate-freshness-audit)
    candidate_freshness_audit_service "$@"
    ;;
  replay-evidence)
    replay_evidence_service "$@"
    ;;
  miner-hash-correlation)
    miner_hash_correlation_service "$@"
    ;;
  single-submit-preimage-trace)
    single_submit_preimage_trace_service "$@"
    ;;
  nomp-parity-audit)
    nomp_parity_audit_service "$@"
    ;;
  js-nomp-oracle)
    js_nomp_oracle_service "$@"
    ;;
  logs)
    logs_service
    ;;
  paths)
    set_effective_defaults
    ensure_runtime_dir
    load_launch_env_if_present
    print_paths
    ;;
  *)
    echo "usage: $0 {start|stop|restart|systemd-restart|status|drill-status|submit-safety-audit|latest-reject|candidate-events [count]|candidate-probability-audit [tail-lines]|share-target-variant-audit [tail-lines]|preimage-reconstruction-audit [tail-lines]|notify-submit-payload-audit [tail-lines]|header-convention-audit [tail-lines]|candidate-followup [count] [--record]|candidate-outcomes [count]|candidate-followup-events [count]|submit-evidence [count]|submit-evidence-find <candidate_hash> [tail_lines]|candidate-freshness-audit [tail_lines]|replay-evidence [count]|miner-hash-correlation <miner-log> [tail-lines]|single-submit-preimage-trace <miner-log> [tail-lines] [--status accepted|rejected] [--job-id <jobId>] [--nonce <nonceHex>]|nomp-parity-audit <miner-log> [tail-lines]|js-nomp-oracle <miner-log> [tail-lines]|logs|paths}" >&2
    exit 1
    ;;
esac
