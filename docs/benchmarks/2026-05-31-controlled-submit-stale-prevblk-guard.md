# Controlled Submit Stale-Prevblk Guard Milestone (2026-05-31)

This document records the milestone achieved during the controlled real-submit drill on 2026-05-31.

## Summary

Following the PEPEPOW block header hash and prevhash helper alignment fixes, candidate validation paths were fully restored. A controlled real-submit drill was executed to verify the validity of candidate detection and the behavior of the stale-prevblk guard mechanism. The guard correctly identified a stale parent block scenario and skipped sending the block template to the daemon.

## Details

### 1. Code Baseline and Audit Clarity
- **Candidate path restoration**: Restored full validation logic aligning the PEPEPOW block header hashing and prevhash handling with the daemon representation (`CheckProofOfWork`).
- **Audit clarity patch**: Applied and committed the candidate freshness audit report adjustments under commit [d82693448b07fb27d8f691fe25e6eac0f3026b9a](file:///home/ubuntu/pool-pepepow/ops/scripts/candidate_freshness_audit.py).
  - Renamed counters to explicit persistent tail counters (`persistent_tail_submit_*_count`) to avoid confusion with active/in-memory process counters.
  - Added warning flag `persistent_tail_counts_may_include_previous_processes: true`.
  - Added latest occurrence timestamp outputs for each tracked category.

### 2. Controlled Submit Drill Execution
- **Drill Parameters**:
  - `PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true`
  - `PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1` (safety-bounded budget)
- **Candidate Event Observed**:
  - **Timestamp**: `2026-05-31T11:12:44Z`
  - **Job ID**: `job-0000000000000007`
  - **Candidate Hash**: `00000008cd9d512d482d5035ceeaab557ea36ccf5de517dcc2d72bc616da5d2f`
- **Submit Decision**: `submit-skipped-stale-prevblk`
  - The local pool logic correctly determined that the candidate's parent block hash did not match the latest block template from the daemon, skipping the submission to prevent a useless stale submission reject.
  - **Submitblock Transmitted**: No (sent count remains at `0`).

### 3. Post-Drill Safety Alignment
- **Runtime config disarmed**: Disarmed real submit block immediately following the event detection.
- **Safety checks**:
  - `real_submit_enabled: False`
  - `safety_status=ok-default-off`

## Remaining Boundaries
- **Pool-found block**: No block has been successfully mined/accepted by the daemon yet under the new hash alignment structure.
- **Payout and round tracking**: Deferred until a valid pool-found block is accepted and confirmed by the PEPEPOW daemon.
