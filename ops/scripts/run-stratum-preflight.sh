#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
POOL_CORE_DIR="${REPO_ROOT}/apps/pool-core"

detect_default_host() {
  local detected
  detected="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -n "${detected}" ]]; then
    printf '%s\n' "${detected}"
    return
  fi
  printf '127.0.0.1\n'
}

OUTPUT_DIR="${PEPEPOW_PREFLIGHT_OUTPUT_DIR:-/tmp/pepepow-preflight}"
BIND_HOST="${PEPEPOW_PREFLIGHT_BIND_HOST:-0.0.0.0}"
PORT="${PEPEPOW_PREFLIGHT_PORT:-39333}"
PUBLIC_HOST="${PEPEPOW_PREFLIGHT_PUBLIC_HOST:-$(detect_default_host)}"
SHARE_DIFFICULTY="${PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY:-1.0}"
JOB_INTERVAL_SECONDS="${PEPEPOW_PREFLIGHT_JOB_INTERVAL_SECONDS:-5}"
CLEAN_OUTPUT="${PEPEPOW_PREFLIGHT_CLEAN_OUTPUT:-1}"

if [[ "${CLEAN_OUTPUT}" == "1" && -d "${OUTPUT_DIR}" ]]; then
  case "${OUTPUT_DIR}" in
    /tmp/*) rm -rf "${OUTPUT_DIR}" ;;
    *)
      echo "Refusing to remove non-/tmp output directory: ${OUTPUT_DIR}" >&2
      exit 1
      ;;
  esac
fi

mkdir -p "${OUTPUT_DIR}"

cat <<EOF
Starting synthetic Stratum preflight
  repo: ${REPO_ROOT}
  bind: ${BIND_HOST}:${PORT}
  advertised endpoint: stratum+tcp://${PUBLIC_HOST}:${PORT}
  output dir: ${OUTPUT_DIR}
  share difficulty: ${SHARE_DIFFICULTY}
  synthetic notify interval: ${JOB_INTERVAL_SECONDS}s

Artifacts
  stratum log: ${OUTPUT_DIR}/stratum.log
  share log: ${OUTPUT_DIR}/share-events.jsonl
  activity snapshot: ${OUTPUT_DIR}/activity-snapshot.json
  runtime snapshot: ${OUTPUT_DIR}/pool-snapshot.json
EOF

cd "${POOL_CORE_DIR}"
env \
  PYTHONUNBUFFERED=1 \
  PEPEPOW_POOL_CORE_STRATUM_BIND_HOST="${BIND_HOST}" \
  PEPEPOW_POOL_CORE_STRATUM_BIND_PORT="${PORT}" \
  PEPEPOW_POOL_CORE_STRATUM_HOST="${PUBLIC_HOST}" \
  PEPEPOW_POOL_CORE_STRATUM_PORT="${PORT}" \
  PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH="${OUTPUT_DIR}/share-events.jsonl" \
  PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_OUTPUT="${OUTPUT_DIR}/activity-snapshot.json" \
  PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT="${OUTPUT_DIR}/pool-snapshot.json" \
  PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY="${SHARE_DIFFICULTY}" \
  PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS="${JOB_INTERVAL_SECONDS}" \
  python3 stratum_ingress.py 2>&1 | tee "${OUTPUT_DIR}/stratum.log"
