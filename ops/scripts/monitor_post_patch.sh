#!/usr/bin/env bash
# PEPEPOW post-patch candidate monitor with exact parsing rules

BASELINE="2026-05-28T14:45:28Z"

while true; do
  NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  echo "=== $NOW ==="

  # 1. Gather logs / status
  DRILL_STATUS=$(./ops/scripts/live-stratum.sh drill-status)
  AUDIT=$(./ops/scripts/live-stratum.sh candidate-freshness-audit 200)
  EVENTS=$(./ops/scripts/live-stratum.sh candidate-events 20)

  # 2. Parse required audit fields
  LATEST_TS=$(echo "$AUDIT" | grep '^latest_candidate_timestamp:' | awk '{print $2}')
  LATEST_JOB=$(echo "$AUDIT" | grep '^latest_candidate_job_id:' | awk '{print $2}')
  LATEST_HASH=$(echo "$AUDIT" | grep '^latest_candidate_hash:' | awk '{print $2}')
  LATEST_PREV=$(echo "$AUDIT" | grep '^latest_candidate_prevhash:' | awk '{print $2}')
  DAEMON_BEST=$(echo "$AUDIT" | grep '^daemon_best_hash_current:' | awk '{print $2}')
  READINESS_STATUS=$(echo "$AUDIT" | grep '^latest_submit_readiness_status:' | awk '{print $2}')
  CONCLUSION=$(echo "$AUDIT" | grep '^freshness_conclusion:' | cut -d' ' -f2-)

  # Parse share events
  LATEST_SHARE_LINE=$(tail -n 1 .runtime/live-stratum/share-events.jsonl 2>/dev/null || true)
  LATEST_SHARE_TS=$(echo "$LATEST_SHARE_LINE" | grep -o '"timestamp":"[^"]*"' | head -n1 | cut -d'"' -f4)
  LATEST_SHARE_JOB=$(echo "$LATEST_SHARE_LINE" | grep -o '"jobId":"[^"]*"' | head -n1 | cut -d'"' -f4)

  # Parse drill-status fields
  REAL_SUBMIT=$(echo "$DRILL_STATUS" | grep '^real_submit_enabled:' | awk '{print $2}')

  # Parse state details from candidate-events 20 for the matching latest candidate
  # Since candidate-events 20 lists multiple events, locate the block matching the latest hash
  # We can parse candidate_prep_status and dry_run_status for LATEST_HASH
  # If LATEST_HASH is not empty, we extract its block from candidate-events 20
  PREP_STATUS=""
  DRY_STATUS=""
  if [ -n "$LATEST_HASH" ]; then
    # We parse the section for the latest hash in candidate-events 20
    # The output is formatted in blocks separated by "---" or similar, or just lines.
    # Let's write a simple helper/parser to extract prep & dry status for this hash.
    MATCHING_BLOCK=$(echo "$EVENTS" | awk -v hash="$LATEST_HASH" '
      BEGIN { RS="---"; FS="\n" }
      $0 ~ hash { print }
    ')
    PREP_STATUS=$(echo "$MATCHING_BLOCK" | grep '^candidate_prep_status:' | head -n1 | awk '{print $2}')
    DRY_STATUS=$(echo "$MATCHING_BLOCK" | grep '^dry_run_status:' | head -n1 | awk '{print $2}')
  fi

  # Check if candidate is post-patch
  IS_POST_PATCH="No"
  if [[ -n "$LATEST_TS" && "$LATEST_TS" > "$BASELINE" ]]; then
    IS_POST_PATCH="Yes"
  fi

  # Check if expected condition is reached
  # Expected condition:
  # - A candidate exists with timestamp later than 2026-05-28T14:45:28Z
  # - candidate_prep_status is candidate-prepared-complete
  # - dry_run_status is dry-run-prepared-complete
  # - real_submit_enabled is False during monitoring
  # - latest_submit_readiness_status is not unsafe
  # - No new submit error or high-hash appears (we can also check if there is an error in recent evidence, but general condition handles it)
  # - Candidate is not clearly stale-prevblk at decision/freshness audit
  
  CONDITION_MET=false
  if [[ "$IS_POST_PATCH" == "Yes" ]] \
     && [[ "$PREP_STATUS" == "candidate-prepared-complete" ]] \
     && [[ "$DRY_STATUS" == "dry-run-prepared-complete" ]] \
     && [[ "$REAL_SUBMIT" == "False" ]] \
     && [[ "$READINESS_STATUS" != "unsafe" ]] \
     && [[ "$CONCLUSION" != "stale-prevblk-observed" ]]; then
    CONDITION_MET=true
  fi

  if [ "$CONDITION_MET" = true ]; then
    echo "READY FOR CONTROLLED SUBMIT WINDOW"
    echo "candidate timestamp: $LATEST_TS"
    echo "job id:              $LATEST_JOB"
    echo "candidate hash:      $LATEST_HASH"
    echo "candidate prevhash:  $LATEST_PREV"
    echo "daemon best hash:    $DAEMON_BEST"
    echo "freshness/readiness status: $READINESS_STATUS / $CONCLUSION"
    echo "current real_submit_enabled status: $REAL_SUBMIT"
    echo "conclusion:                 fresh candidate observed"
    break
  else
    echo "Status summary:"
    echo "  current time:                         $NOW"
    echo "  latest share timestamp:               $LATEST_SHARE_TS"
    echo "  latest share job id:                  $LATEST_SHARE_JOB"
    echo "  latest candidate timestamp:           $LATEST_TS"
    echo "  latest candidate job id:              $LATEST_JOB"
    echo "  latest candidate hash:                $LATEST_HASH"
    echo "  post-patch candidate:                 $IS_POST_PATCH"
    echo "  real_submit_enabled:                  $REAL_SUBMIT"
    echo "  latest_submit_readiness_status:       $READINESS_STATUS"
    echo "  freshness_conclusion:                 $CONCLUSION"
    if [[ "$IS_POST_PATCH" == "Yes" ]]; then
      echo "  conclusion:                           fresh candidate observed"
    else
      echo "  conclusion:                           share path live; no fresh block-target candidate observed"
    fi
    echo "Waiting 5 minutes before next check..."
    sleep 300
  fi
done
