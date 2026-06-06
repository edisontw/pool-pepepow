# Accepted Candidate Observation Surface Verification

Date: 2026-06-06
Status: Finalized & Smoke Tested

## Overview
This document records the verification of the read-only accepted candidate observation surface. This surface is designed to safely expose candidate verification details from the Stratum submitblock outcomes to the public API and frontend without enabling payout mechanics or production submit pathways.

## Components Verified

### 1. Accepted Candidate Lifecycle Tracker
- **Mechanism**: Reads outcomes from the candidate outcome log out-of-band and compiles them into a structured snapshot `accepted-candidates.json`.
- **Status Lifecycle**: Successfully records block details, daemon acceptance status (e.g. `submitblock_daemon_accepted_likely`), and chain match statuses (`lifecycleStatus` mapping to `chain_match_found`, `chain_match_not_found`, etc.).
- **Log Source**: Processes event logs in a bounded manner without doing full runtime scans on request paths.

### 2. Public API: `/api/accepted-candidates`
- **Output Format**: Returns JSON payload with the expected shape under `{"items": [...]}` where candidate properties are formatted in `camelCase` to match the frontend expectations.
- **Robustness**: Properly handles a missing or malformed snapshot file by returning an empty list (`{"items": []}`) fallback rather than raising internal errors or 500 responses.
- **Path Resolution**: Modified to prioritize reading from the live stratum runtime directory `activity_snapshot_path.parent` first, falling back to the standard snapshot path if needed, which guarantees that it matches the live operational state.

### 3. Frontend Observation Surface
- **Location**: Rendered on the Blocks page (`/blocks.html`) under the **Accepted pool candidates / chain match** section.
- **Visual & Structural Clarity**: Explicitly contains no maturity, reward, balance, or PPLNS wording. Under no circumstances are candidates labeled as "payable".
- **Wording Notice**: An explicit notice is rendered on the blocks table to clarify that payout and round accounting are paused, and candidates are not payout-ready.

---

## Safety Configurations

- **Real Submit Status**: `real_submit_enabled` remains **default-off** (configured as `false`). No live blocks will be submitted to the daemon from normal miner shares.
- **Payout Handling**: Payout scripts, payout logic, and distribution loops remain paused.
- **Round Accounting**: Round accounting processes are paused.
