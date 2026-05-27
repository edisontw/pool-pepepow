# Progress Note: Armed Submit Window Wrapper and Safety Drill
**Date**: 2026-05-26  
**Status**: Milestone Reached (Safety wrapper implemented, live drill executed, casing bug fixed)

## 1. Unified Command Wrapper
We added a new subcommand wrapper to coordinate the armed submit drill flow:
```bash
./ops/scripts/live-stratum.sh submit-arm-watch-once [seconds]
```

## 2. Rationale
The older two-step flow was operator-error-prone. If an operator triggered `submit-arm-once` but failed to run `submit-watch-once` (due to typos or terminal interruptions), the pool would remain in an armed (`real_submit_enabled=true`) state. 
The new wrapper ensures a single command execution handles:
$$\text{Arm} \rightarrow \text{Watch} \rightarrow \text{Always Disarm} \rightarrow \text{Final Safety Summary}$$
Using signal traps (INT, TERM, EXIT), it guarantees that the pool is returned to the default-off safety state under all exit conditions.

## 3. Live Drill Result
A live bounded drill was executed using the new unified wrapper:
```bash
./ops/scripts/live-stratum.sh submit-arm-watch-once 600
```
- **Terminal Event Observed**: `submit-sent`
- **Candidate Block Details**:
  - **Timestamp**: `2026-05-26T16:27:31Z`
  - **Job ID**: `job-0000000000000019`
  - **Candidate Block Hash**: `00000002e37d152f579355c47a5f0317226b7e823f9415865da43195c5b41ef7`
- **Final Safety Status**:
  - `final_real_submit_enabled`: `False`
  - `safety_status`: `ok-default-off`
- **Follow-up / Outcome**: `no-match-found` / `chain-match-not-found` on local chain.

## 4. Follow-up Casing Normalization Fix
A post-drill validation revealed that Python-style boolean outputs (`False` / `True`) in system activity snapshots caused the casing-sensitive shell assertions to trigger false-positive warnings (`watch_status: failed`).
We patched `ops/scripts/live-stratum.sh` to normalize the values to lowercase before comparison:
- `False` and `false` are treated as **safe** (exit 0).
- `True`, `true`, `unknown`, and empty values remain **unsafe** (trigger warnings and non-zero exit).

## 5. Operational Interpretation
- **Candidate Prep & Dry-Run**: Functioning correctly and producing valid candidate blocks.
- **Controlled Submissions**: Effectively transmitted block payloads to the daemon RPC during the armed window.
- **Safety Restoration**: The wrapper successfully disarms and enforces default-off safety at exit.
- **Block Propagation**: The drill does not prove confirmed block discovery on the network, and payout readiness is not yet established.

## 6. Remaining Boundaries & Next Steps
- Further investigation is needed to clarify why the submitted candidate block hashes result in `chain-match-not-found` on the local node.
- Hashing, target math, merkle logic, and header conventions should remain frozen unless concrete contradictory evidence is uncovered.
- Real submits must remain default-off. Use only the `submit-arm-watch-once` command wrapper for all future drills.

***

## Validation Details
- **Syntax Check**: `bash -n ops/scripts/live-stratum.sh` passed successfully.
- **Drill Status Check**: Verified `real_submit_enabled=False`.
- **Safety Audit Check**: Verified `safety_status=ok-default-off`.
- **Casing Normalization Simulation**: Checked behavior of safety evaluation script against simulated values:
  - `False` / `false` $\rightarrow$ SAFE (exit 0)
  - `True` / `true` / `unknown` / `""` $\rightarrow$ UNSAFE (exit 1)
