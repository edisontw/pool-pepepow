# Public MVP Surface Deploy Readiness Note - 2026-06-06

This document records the final verification and readiness status of the PEPEPOW pool MVP public surface.

## Surface Status

- **Accepted Candidates Read-Only Surface**: Finalized and restricted toapproved lifecycle observation schema (candidate hash, job ID, submit timestamp, daemon result, followup status, matched height, matched block hash, and lifecycle status). Out-of-scope confirmations and daemon accepted-likely metrics are removed.
- **Miner Lookup Visibility**: Improved to render active worker count and accepted shares count under the miner summary cards, and accepted shares count in the individual workers table.
- **Empty-State Clarity**: Custom empty-state messages implemented for blocks, accepted candidates, and payments tables to clearly inform users of the paused payout status and default-off block submission status.
- **Real Submit Status**: Default-off (`real_submit_enabled: False`).
- **Payout & Round Accounting**: Remain paused; payments remain placeholder data.

## Verification & Smoke Checks

The following commands were executed to verify deploy readiness:

### Focused Test Suites
```bash
# Verify API Endpoints and Fallbacks
PYTHONPATH=apps/api python3 -m unittest tests/test_api_endpoints.py

# Validate Shell Script Syntax
bash -n ops/scripts/*.sh
```
Status: **PASS** (15 tests ran successfully, all shell scripts syntax OK).

### Stratum and Candidate Smoke Checks
```bash
# Check controlled drill status
./ops/scripts/live-stratum.sh drill-status

# Generate accepted candidates JSON snapshot
./ops/scripts/live-stratum.sh accepted-candidates
```
Status: **PASS** (Stratum drill status reports ready and submit disabled; accepted candidates successfully saved).
