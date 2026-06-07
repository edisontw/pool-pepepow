#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUNTIME_DIR="${PEPEPOW_LIVE_STRATUM_RUNTIME_DIR:-${REPO_ROOT}/.runtime/live-stratum}"

APPLY=false
for arg in "$@"; do
  if [[ "$arg" == "--apply" ]]; then
    APPLY=true
  fi
done

PEPEPOW_RETENTION_LOG_MAX_MB="${PEPEPOW_RETENTION_LOG_MAX_MB:-10}"
PEPEPOW_RETENTION_JSONL_MAX_MB="${PEPEPOW_RETENTION_JSONL_MAX_MB:-100}"

if [[ ! "${PEPEPOW_RETENTION_LOG_MAX_MB}" =~ ^[0-9]+$ ]]; then
  echo "Error: PEPEPOW_RETENTION_LOG_MAX_MB must be an integer" >&2
  exit 1
fi
if [[ ! "${PEPEPOW_RETENTION_JSONL_MAX_MB}" =~ ^[0-9]+$ ]]; then
  echo "Error: PEPEPOW_RETENTION_JSONL_MAX_MB must be an integer" >&2
  exit 1
fi

max_log_bytes=$(( PEPEPOW_RETENTION_LOG_MAX_MB * 1024 * 1024 ))
max_jsonl_bytes=$(( PEPEPOW_RETENTION_JSONL_MAX_MB * 1024 * 1024 ))

is_critical_jsonl() {
  local filename
  filename="$(basename "$1")"
  
  if [[ "$filename" == "payment-actions.jsonl" ]] || \
     [[ "$filename" == *payment*.jsonl ]] || \
     [[ "$filename" == *payout*.jsonl ]] || \
     [[ "$filename" == *candidate*outcome*.jsonl ]] || \
     [[ "$filename" == *candidate*followup*.jsonl ]] || \
     [[ "$filename" == *accepted*candidate*.jsonl ]]; then
    return 0
  fi
  return 1
}

rotate_file() {
  local file_path="$1"
  local timestamp
  timestamp="$(date +%Y%m%d-%H%M%S)"
  local archive_path="${file_path}.${timestamp}"
  
  mv "${file_path}" "${archive_path}"
  gzip "${archive_path}"
  touch "${file_path}"
}

log_rotate_candidates=0
jsonl_archive_candidates=0
skipped_critical_jsonl=0
skipped_snapshots=0
old_archives_to_remove=0

rotated_logs=0
archived_jsonl=0
removed_old_archives=0

if [[ -d "${RUNTIME_DIR}" ]]; then
  shopt -s nullglob
  for f in "${RUNTIME_DIR}"/*; do
    if [[ ! -f "$f" ]]; then
      continue
    fi
    
    filename="$(basename "$f")"
    
    if [[ "$filename" == *.log ]]; then
      size_bytes="$(stat -c '%s' "$f")"
      if (( size_bytes >= max_log_bytes )); then
        log_rotate_candidates=$(( log_rotate_candidates + 1 ))
        if [[ "$APPLY" == "true" ]]; then
          rotate_file "$f"
          rotated_logs=$(( rotated_logs + 1 ))
        fi
      fi
    elif [[ "$filename" == *.jsonl ]]; then
      if is_critical_jsonl "$filename"; then
        skipped_critical_jsonl=$(( skipped_critical_jsonl + 1 ))
      else
        size_bytes="$(stat -c '%s' "$f")"
        if (( size_bytes >= max_jsonl_bytes )); then
          jsonl_archive_candidates=$(( jsonl_archive_candidates + 1 ))
          if [[ "$APPLY" == "true" ]]; then
            rotate_file "$f"
            archived_jsonl=$(( archived_jsonl + 1 ))
          fi
        fi
      fi
    elif [[ "$filename" == *.json ]]; then
      skipped_snapshots=$(( skipped_snapshots + 1 ))
    fi
  done
  shopt -u nullglob
fi

if [[ -d "${RUNTIME_DIR}" ]]; then
  basenames=()
  shopt -s nullglob
  for f in "${RUNTIME_DIR}"/*.log "${RUNTIME_DIR}"/*.jsonl; do
    if [[ -f "$f" ]]; then
      basenames+=("$(basename "$f")")
    fi
  done
  for f in "${RUNTIME_DIR}"/*; do
    if [[ -f "$f" ]]; then
      fname="$(basename "$f")"
      if [[ "$fname" =~ ^(.+\.(log|jsonl))\.[0-9]{8}-[0-9]{6}\.gz$ ]]; then
        basenames+=("${BASH_REMATCH[1]}")
      fi
    fi
  done
  shopt -u nullglob
  
  if [ ${#basenames[@]} -gt 0 ]; then
    unique_basenames=($(printf '%s\n' "${basenames[@]}" | sort -u))
    
    for base in "${unique_basenames[@]}"; do
      archives=()
      for f in "${RUNTIME_DIR}"/*; do
        if [[ -f "$f" ]]; then
          fname="$(basename "$f")"
          if [[ "$fname" =~ ^${base}\.[0-9]{8}-[0-9]{6}\.gz$ ]]; then
            archives+=("$f")
          fi
        fi
      done
      
      if [ ${#archives[@]} -gt 0 ]; then
        sorted_archives=()
        while IFS= read -r line; do
          if [[ -n "$line" ]]; then
            sorted_archives+=("$line")
          fi
        done < <(printf '%s\n' "${archives[@]}" | sort)
        
        num_archives=${#sorted_archives[@]}
        if (( num_archives > 7 )); then
          excess=$(( num_archives - 7 ))
          for (( i=0; i<excess; i++ )); do
            archive_to_del="${sorted_archives[i]}"
            old_archives_to_remove=$(( old_archives_to_remove + 1 ))
            if [[ "$APPLY" == "true" ]]; then
              rm -f "$archive_to_del"
              removed_old_archives=$(( removed_old_archives + 1 ))
            fi
          done
        fi
      fi
    done
  fi
fi

if [[ "$APPLY" == "true" ]]; then
  cat <<EOF
runtime_retention: applied
rotated_logs: ${rotated_logs}
archived_jsonl: ${archived_jsonl}
removed_old_archives: ${removed_old_archives}
skipped_critical_jsonl: ${skipped_critical_jsonl}
EOF
else
  action_required="false"
  if (( log_rotate_candidates > 0 || jsonl_archive_candidates > 0 || old_archives_to_remove > 0 )); then
    action_required="true"
  fi
  cat <<EOF
runtime_retention: dry-run
runtime_dir: ${RUNTIME_DIR}
log_rotate_candidates: ${log_rotate_candidates}
jsonl_archive_candidates: ${jsonl_archive_candidates}
skipped_critical_jsonl: ${skipped_critical_jsonl}
skipped_snapshots: ${skipped_snapshots}
action_required: ${action_required}
EOF
fi
