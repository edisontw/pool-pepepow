# Benchmark: Round Accounting Refresh and Attribution (2026-06-06)

## Overview
We audited and verified the correctness of the read-only round accounting attribution and its automated refresh systemd timer on MN5 under live data. 

## Key Properties
- **Deployment & Automation**: 
  - `pepepow-pool-rounds-refresh.timer` and `pepepow-pool-rounds-refresh.service` were successfully deployed and verified to run every 1 minute.
  - The script executes in `0.44` seconds, well under the `0.6` seconds budget constraint.
- **Round Boundary Correctness**:
  - Validated that rounds are chronologically ordered by `submit_timestamp`.
  - Confirmed the strict half-open interval boundary `(start_ts, c_ts]` is correctly applied when attributing shares, preventing duplicate share counting.
  - Verified that duplicate submit timestamps are handled deterministically (empty range for duplicate timestamps, preventing duplicate share attribution).
- **Share Attribution Filters**:
  - Excluded rejected/invalid shares.
  - Excluded low-difficulty shares (filtering against the `assumedShareDifficulty` threshold, e.g., `0.00025` on MN5).
  - Excluded malformed shares (e.g. missing wallet/login fields).
  - Verified login string resolution (`wallet.worker`) correctly strips worker suffixes and attributes shares to both root wallet and worker identities.
  - Clarified round accounting semantics: separated raw accepted share count (`total_share_count` / `Shares`) from difficulty score totals (`total_share_score` / `Score`), clarifying that the previous `total shares 0.5309999999999993` represented the accumulated difficulty/score contribution, not the raw share count.
- **Security & Safety Isolation**:
  - Confirmed confirmed rounds strictly omit `payable`, `balance`, `earned`, `paid`, and `reward-ready` fields to avoid any payout exposure.
  - All operations are completely read-only and decoupled from wallet/payout execution.
