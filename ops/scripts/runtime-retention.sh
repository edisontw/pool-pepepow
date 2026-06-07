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

is_eligible_operational_jsonl() {
  local filename
  filename="$(basename "$1")"
  if [[ "$filename" == "submit-evidence.jsonl" ]] || \
     [[ "$filename" == "notify-evidence.jsonl" ]] || \
     [[ "$filename" == "notify-debug-capture.jsonl" ]] || \
     [[ "$filename" == "share-hash-probe.jsonl" ]]; then
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

get_archive_group() {
  local filename="$1"
  if [[ "$filename" =~ ^share-events.*\.gz$ ]]; then
    echo "share-events"
  elif [[ "$filename" =~ ^(.+\.(log|jsonl))\.[0-9]{8}-[0-9]{6}\.gz$ ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo ""
  fi
}

log_rotate_candidates=0
jsonl_archive_candidates=0
share_segment_archive_candidates=0
skipped_critical_jsonl=0
skipped_snapshots=0
removed_old_archives=0

# 1. Process active files (logs and jsonls)
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
        fi
      fi
    elif [[ "$filename" == *.jsonl ]]; then
      if [[ "$filename" == "share-events.jsonl" ]]; then
        size_bytes="$(stat -c '%s' "$f")"
        if (( size_bytes >= max_jsonl_bytes )); then
          jsonl_archive_candidates=$(( jsonl_archive_candidates + 1 ))
          if [[ "$APPLY" == "true" ]]; then
            rotate_file "$f"
          fi
        fi
      elif [[ "$filename" =~ ^share-events\..+\.jsonl$ ]]; then
        # Treated separately as share segment candidates
        :
      elif is_eligible_operational_jsonl "$filename"; then
        size_bytes="$(stat -c '%s' "$f")"
        if (( size_bytes >= max_jsonl_bytes )); then
          jsonl_archive_candidates=$(( jsonl_archive_candidates + 1 ))
          if [[ "$APPLY" == "true" ]]; then
            rotate_file "$f"
          fi
        fi
      else
        skipped_critical_jsonl=$(( skipped_critical_jsonl + 1 ))
      fi
    elif [[ "$filename" == *.json ]]; then
      skipped_snapshots=$(( skipped_snapshots + 1 ))
    fi
  done
  shopt -u nullglob
fi

# 2. Treat share event rotated segments specially
share_segments=()
if [[ -d "${RUNTIME_DIR}" ]]; then
  shopt -s nullglob
  for f in "${RUNTIME_DIR}"/share-events.*.jsonl; do
    if [[ -f "$f" ]]; then
      share_segments+=("$f")
    fi
  done
  shopt -u nullglob
fi

if [ ${#share_segments[@]} -gt 0 ]; then
  sorted_segments=()
  while IFS= read -r line; do
    if [[ -n "$line" ]]; then
      sorted_segments+=("${line#* }")
    fi
  done < <(stat -c '%Y %n' "${share_segments[@]}" 2>/dev/null | sort -n)
  
  num_segments=${#sorted_segments[@]}
  if (( num_segments > 3 )); then
    excess_segments=$(( num_segments - 3 ))
    for (( i=0; i<excess_segments; i++ )); do
      seg_file="${sorted_segments[i]}"
      share_segment_archive_candidates=$(( share_segment_archive_candidates + 1 ))
      if [[ "$APPLY" == "true" ]]; then
        gzip "${seg_file}"
      fi
    done
  fi
fi

# 3. Clean up compressed archives (keeping latest 7 per basename/prefix)
archive_groups=()
if [[ -d "${RUNTIME_DIR}" ]]; then
  shopt -s nullglob
  for f in "${RUNTIME_DIR}"/*.gz; do
    group="$(get_archive_group "$(basename "$f")")"
    if [[ -n "$group" ]]; then
      archive_groups+=("$group")
    fi
  done
  shopt -u nullglob
fi

if [ ${#archive_groups[@]} -gt 0 ]; then
  unique_groups=($(printf '%s\n' "${archive_groups[@]}" | sort -u))
  for group in "${unique_groups[@]}"; do
    group_files=()
    shopt -s nullglob
    for f in "${RUNTIME_DIR}"/*.gz; do
      if [[ "$(get_archive_group "$(basename "$f")")" == "$group" ]]; then
        group_files+=("$f")
      fi
    done
    shopt -u nullglob
    
    sorted_files=()
    if [ ${#group_files[@]} -gt 0 ]; then
      while IFS= read -r line; do
        if [[ -n "$line" ]]; then
          sorted_files+=("${line#* }")
        fi
      done < <(stat -c '%Y %n' "${group_files[@]}" 2>/dev/null | sort -n)
    fi
    
    num_files=${#sorted_files[@]}
    if (( num_files > 7 )); then
      excess=$(( num_files - 7 ))
      for (( i=0; i<excess; i++ )); do
        archive_to_del="${sorted_files[i]}"
        removed_old_archives=$(( removed_old_archives + 1 ))
        if [[ "$APPLY" == "true" ]]; then
          rm -f "$archive_to_del"
        fi
      done
    fi
  done
fi

action_required="false"
if (( log_rotate_candidates > 0 || jsonl_archive_candidates > 0 || share_segment_archive_candidates > 0 || removed_old_archives > 0 )); then
  action_required="true"
fi

if [[ "$APPLY" == "true" ]]; then
  status_mode="applied"
else
  status_mode="dry-run"
fi

cat <<EOF
runtime_retention: ${status_mode}
runtime_dir: ${RUNTIME_DIR}
log_rotate_candidates: ${log_rotate_candidates}
jsonl_archive_candidates: ${jsonl_archive_candidates}
share_segment_archive_candidates: ${share_segment_archive_candidates}
skipped_critical_jsonl: ${skipped_critical_jsonl}
skipped_snapshots: ${skipped_snapshots}
removed_old_archives: ${removed_old_archives}
action_required: ${action_required}
EOF
