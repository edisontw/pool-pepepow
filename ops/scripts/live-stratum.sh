#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
POOL_CORE_DIR="${REPO_ROOT}/apps/pool-core"
RUNTIME_DIR="${REPO_ROOT}/.runtime/live-stratum"
PID_FILE="${RUNTIME_DIR}/stratum.pid"
LOG_FILE="${RUNTIME_DIR}/stratum.log"
SHARE_LOG="${RUNTIME_DIR}/share-events.jsonl"
ACTIVITY_SNAPSHOT="${RUNTIME_DIR}/activity-snapshot.json"
LAUNCH_ENV_FILE="${RUNTIME_DIR}/launch.env"

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

PORT=""
PUBLIC_HOST=""
BIND_HOST=""
SHARE_DIFFICULTY=""
JOB_INTERVAL_SECONDS=""
SNAPSHOT_INTERVAL_SECONDS=""
LOG_ROTATE_BYTES=""
TEMPLATE_MODE=""
TEMPLATE_FETCH_INTERVAL_SECONDS=""
TEMPLATE_JOB_TTL_SECONDS=""
TEMPLATE_JOB_CACHE_SIZE=""
RPC_HOST=""
RPC_PORT=""
RPC_URL=""
RPC_USER=""
RPC_PASSWORD=""
RPC_TIMEOUT_SECONDS=""

set_effective_defaults() {
  local detected_rpc_host detected_rpc_port
  detected_rpc_host="${PEPEPOWD_RPC_HOST:-127.0.0.1}"
  detected_rpc_port="${PEPEPOWD_RPC_PORT:-8834}"
  PORT="${PEPEPOW_POOL_CORE_STRATUM_BIND_PORT:-39333}"
  PUBLIC_HOST="${PEPEPOW_POOL_CORE_STRATUM_HOST:-$(detect_default_host)}"
  BIND_HOST="${PEPEPOW_POOL_CORE_STRATUM_BIND_HOST:-0.0.0.0}"
  SHARE_DIFFICULTY="${PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY:-0.00000001}"
  JOB_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS:-5}"
  SNAPSHOT_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS:-1}"
  LOG_ROTATE_BYTES="${PEPEPOW_LIVE_STRATUM_LOG_ROTATE_BYTES:-33554432}"
  TEMPLATE_MODE="${PEPEPOW_POOL_CORE_TEMPLATE_MODE:-synthetic}"
  TEMPLATE_FETCH_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_TEMPLATE_FETCH_INTERVAL_SECONDS:-15}"
  TEMPLATE_JOB_TTL_SECONDS="${PEPEPOW_POOL_CORE_TEMPLATE_JOB_TTL_SECONDS:-180}"
  TEMPLATE_JOB_CACHE_SIZE="${PEPEPOW_POOL_CORE_TEMPLATE_JOB_CACHE_SIZE:-64}"
  RPC_HOST="${detected_rpc_host}"
  RPC_PORT="${detected_rpc_port}"
  RPC_URL="${PEPEPOWD_RPC_URL:-http://${detected_rpc_host}:${detected_rpc_port}}"
  RPC_USER="${PEPEPOWD_RPC_USER:-}"
  RPC_PASSWORD="${PEPEPOWD_RPC_PASSWORD:-}"
  RPC_TIMEOUT_SECONDS="${PEPEPOWD_RPC_TIMEOUT_SECONDS:-5}"
}

ensure_runtime_dir() {
  mkdir -p "${RUNTIME_DIR}"
}

load_launch_env_if_present() {
  local loaded_bind_host loaded_port loaded_public_host
  local loaded_share_difficulty loaded_job_interval loaded_snapshot_interval
  local loaded_template_mode loaded_template_fetch_interval
  local loaded_template_job_ttl loaded_template_job_cache_size
  local loaded_rpc_host loaded_rpc_port loaded_rpc_url
  local loaded_rpc_user loaded_rpc_password loaded_rpc_timeout

  if [[ ! -f "${LAUNCH_ENV_FILE}" ]]; then
    return
  fi

  loaded_bind_host="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_BIND_HOST)"
  loaded_port="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_BIND_PORT)"
  loaded_public_host="$(launch_env_value PEPEPOW_POOL_CORE_STRATUM_HOST)"
  loaded_share_difficulty="$(launch_env_value PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY)"
  loaded_job_interval="$(launch_env_value PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS)"
  loaded_snapshot_interval="$(launch_env_value PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS)"
  loaded_template_mode="$(launch_env_value PEPEPOW_POOL_CORE_TEMPLATE_MODE)"
  loaded_template_fetch_interval="$(launch_env_value PEPEPOW_POOL_CORE_TEMPLATE_FETCH_INTERVAL_SECONDS)"
  loaded_template_job_ttl="$(launch_env_value PEPEPOW_POOL_CORE_TEMPLATE_JOB_TTL_SECONDS)"
  loaded_template_job_cache_size="$(launch_env_value PEPEPOW_POOL_CORE_TEMPLATE_JOB_CACHE_SIZE)"
  loaded_rpc_host="$(launch_env_value PEPEPOWD_RPC_HOST)"
  loaded_rpc_port="$(launch_env_value PEPEPOWD_RPC_PORT)"
  loaded_rpc_url="$(launch_env_value PEPEPOWD_RPC_URL)"
  loaded_rpc_user="$(launch_env_value PEPEPOWD_RPC_USER)"
  loaded_rpc_password="$(launch_env_value PEPEPOWD_RPC_PASSWORD)"
  loaded_rpc_timeout="$(launch_env_value PEPEPOWD_RPC_TIMEOUT_SECONDS)"

  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_BIND_HOST+x}" && -n "${loaded_bind_host}" ]]; then
    BIND_HOST="${loaded_bind_host}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_BIND_PORT+x}" && -n "${loaded_port}" ]]; then
    PORT="${loaded_port}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_STRATUM_HOST+x}" && -n "${loaded_public_host}" ]]; then
    PUBLIC_HOST="${loaded_public_host}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY+x}" && -n "${loaded_share_difficulty}" ]]; then
    SHARE_DIFFICULTY="${loaded_share_difficulty}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS+x}" && -n "${loaded_job_interval}" ]]; then
    JOB_INTERVAL_SECONDS="${loaded_job_interval}"
  fi
  if [[ -z "${PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS+x}" && -n "${loaded_snapshot_interval}" ]]; then
    SNAPSHOT_INTERVAL_SECONDS="${loaded_snapshot_interval}"
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
effective_difficulty: ${SHARE_DIFFICULTY}
difficulty_source: ${LAUNCH_ENV_FILE} -> PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY
notify_interval_seconds: ${JOB_INTERVAL_SECONDS}
template_mode: ${TEMPLATE_MODE}
template_fetch_interval_seconds: ${TEMPLATE_FETCH_INTERVAL_SECONDS}
template_job_ttl_seconds: ${TEMPLATE_JOB_TTL_SECONDS}
template_job_cache_size: ${TEMPLATE_JOB_CACHE_SIZE}
rpc_host: ${RPC_HOST}
rpc_port: ${RPC_PORT}
rpc_url: ${RPC_URL}
rpc_user: ${RPC_USER:-unset}
rpc_password: $(masked_rpc_password)
rpc_timeout_seconds: ${RPC_TIMEOUT_SECONDS}
runtime_dir: ${RUNTIME_DIR}
pid_file: ${PID_FILE}
log_file: ${LOG_FILE}
share_log: ${SHARE_LOG}
activity_snapshot: ${ACTIVITY_SNAPSHOT}
launch_env: ${LAUNCH_ENV_FILE}
EOF
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
PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS=${JOB_INTERVAL_SECONDS}
PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS=${SNAPSHOT_INTERVAL_SECONDS}
PEPEPOW_POOL_CORE_TEMPLATE_MODE=${TEMPLATE_MODE}
PEPEPOW_POOL_CORE_TEMPLATE_FETCH_INTERVAL_SECONDS=${TEMPLATE_FETCH_INTERVAL_SECONDS}
PEPEPOW_POOL_CORE_TEMPLATE_JOB_TTL_SECONDS=${TEMPLATE_JOB_TTL_SECONDS}
PEPEPOW_POOL_CORE_TEMPLATE_JOB_CACHE_SIZE=${TEMPLATE_JOB_CACHE_SIZE}
PEPEPOWD_RPC_HOST=${RPC_HOST}
PEPEPOWD_RPC_PORT=${RPC_PORT}
PEPEPOWD_RPC_URL=${RPC_URL}
PEPEPOWD_RPC_USER=${RPC_USER}
PEPEPOWD_RPC_PASSWORD=${RPC_PASSWORD}
PEPEPOWD_RPC_TIMEOUT_SECONDS=${RPC_TIMEOUT_SECONDS}
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
print(f"active_job_count: {meta.get('activeJobCount')}")
PY
}

print_runtime_sizes() {
  for path in "${LOG_FILE}" "${SHARE_LOG}" "${ACTIVITY_SNAPSHOT}"; do
    if [[ -f "${path}" ]]; then
      printf 'size_bytes[%s]: %s\n' "$(basename "${path}")" "$(stat -c '%s' "${path}")"
    fi
  done
}

start_service() {
  set_effective_defaults
  ensure_runtime_dir
  load_launch_env_if_present
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
    export PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS="${JOB_INTERVAL_SECONDS}"
    export PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS="${SNAPSHOT_INTERVAL_SECONDS}"
    export PEPEPOW_POOL_CORE_TEMPLATE_MODE="${TEMPLATE_MODE}"
    export PEPEPOW_POOL_CORE_TEMPLATE_FETCH_INTERVAL_SECONDS="${TEMPLATE_FETCH_INTERVAL_SECONDS}"
    export PEPEPOW_POOL_CORE_TEMPLATE_JOB_TTL_SECONDS="${TEMPLATE_JOB_TTL_SECONDS}"
    export PEPEPOW_POOL_CORE_TEMPLATE_JOB_CACHE_SIZE="${TEMPLATE_JOB_CACHE_SIZE}"
    export PEPEPOWD_RPC_HOST="${RPC_HOST}"
    export PEPEPOWD_RPC_PORT="${RPC_PORT}"
    export PEPEPOWD_RPC_URL="${RPC_URL}"
    export PEPEPOWD_RPC_USER="${RPC_USER}"
    export PEPEPOWD_RPC_PASSWORD="${RPC_PASSWORD}"
    export PEPEPOWD_RPC_TIMEOUT_SECONDS="${RPC_TIMEOUT_SECONDS}"
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
  stop_service
  set_effective_defaults
  start_service
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
  status)
    status_service
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
    echo "usage: $0 {start|stop|restart|status|logs|paths}" >&2
    exit 1
    ;;
esac
