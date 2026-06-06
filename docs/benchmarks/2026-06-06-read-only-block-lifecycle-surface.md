# Benchmark: Read-Only Block Lifecycle Surface (2026-06-06)

## Overview
We have designed and deployed the smallest read-only block lifecycle tracking surface for accepted pool candidates. The system correlates candidates with the public network snapshot to track their confirmation progress and chain maturity states.

## Key Properties
- **Read-Only Lifecycle Statuses**: Added `candidate_recorded`, `submit_accepted`, `chain_match_found`, `immature`, `confirmed`, and `orphan` tracking.
- **Confirmations & Chain Maturity**: Matched height and confirmations are resolved out-of-band by correlating candidate outcome events with recent snapshot blocks and current height. These fields are strictly for observation.
- **Zero Balance or Payout Exposure**: No payout accounting is implemented. No balance details are computed or shown. Frontend miner lookups explicitly omit balance metrics to prevent any implication of payout readiness.
- **Safe Network Isolation**: Real submitblock logic remains default-off (`real_submit_enabled: False` via budget constraints/configuration). Wallet RPC remains unexposed and untouched.
- **Smoke Testing Success**: Public API endpoints `/api/accepted-candidates` and frontend dashboards are verified stable and render the new columns and observations correctly.
