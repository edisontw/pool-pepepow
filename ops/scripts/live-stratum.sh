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

clear_shell_loaded_launch_env() {
  unset PEPEPOW_POOL_CORE_STRATUM_BIND_HOST
  unset PEPEPOW_POOL_CORE_STRATUM_BIND_PORT
  unset PEPEPOW_POOL_CORE_STRATUM_PORT
  unset PEPEPOW_POOL_CORE_STRATUM_HOST
  unset PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH
  unset PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_OUTPUT
  unset PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY
  unset PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS
  unset PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS
}

set_effective_defaults() {
  PORT="${PEPEPOW_POOL_CORE_STRATUM_BIND_PORT:-39333}"
  PUBLIC_HOST="${PEPEPOW_POOL_CORE_STRATUM_HOST:-$(detect_default_host)}"
  BIND_HOST="${PEPEPOW_POOL_CORE_STRATUM_BIND_HOST:-0.0.0.0}"
  SHARE_DIFFICULTY="${PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY:-0.00000001}"
  JOB_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS:-5}"
  SNAPSHOT_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS:-1}"
}

ensure_runtime_dir() {
  mkdir -p "${RUNTIME_DIR}"
}

load_launch_env_if_present() {
  if [[ -f "${LAUNCH_ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${LAUNCH_ENV_FILE}"
    PORT="${PEPEPOW_POOL_CORE_STRATUM_BIND_PORT:-${PORT}}"
    PUBLIC_HOST="${PEPEPOW_POOL_CORE_STRATUM_HOST:-${PUBLIC_HOST}}"
    BIND_HOST="${PEPEPOW_POOL_CORE_STRATUM_BIND_HOST:-${BIND_HOST}}"
    SHARE_DIFFICULTY="${PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY:-${SHARE_DIFFICULTY}}"
    JOB_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS:-${JOB_INTERVAL_SECONDS}}"
    SNAPSHOT_INTERVAL_SECONDS="${PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS:-${SNAPSHOT_INTERVAL_SECONDS}}"
  fi
}

print_paths() {
  cat <<EOF
endpoint: stratum+tcp://${PUBLIC_HOST}:${PORT}
bind: ${BIND_HOST}:${PORT}
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

write_launch_env() {
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
PYTHONUNBUFFERED=1
EOF
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
PY
}

start_service() {
  clear_shell_loaded_launch_env
  set_effective_defaults
  ensure_runtime_dir
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
