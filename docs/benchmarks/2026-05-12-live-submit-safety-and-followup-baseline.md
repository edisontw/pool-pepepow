# 2026-05-12 Live Submit Safety and Follow-up Baseline

## Summary

This record fills the benchmark / progress gap after the `2026-04-30 Live Fixed Difficulty Baseline 0.00025`.

The post-2026-04-30 work moved from fixed-difficulty live observation into controlled real-submit safety checks, candidate follow-up, stale-prevblk protection, and restoration of the default-off submit baseline.

This is an operational benchmark / progress record. It does **not** claim:

- confirmed block discovery
- payout readiness
- round tracking readiness
- full production pool completion

---

## Continuity From 2026-04-30

The prior live baseline was:

- effective share difficulty: `0.00025`
- miner wire difficulty: `16.384`
- difficulty scale: `65536`
- vardiff: `false`
- low-diff share-event throttle: every `10`
- clean rollover behavior: `mining.set_difficulty` before `mining.notify`

The 2026-04-30 fresh miner window showed:

- accepted-share flow restored
- rejects remained cleanly `low-difficulty-share` only
- stale submits: `0`
- unknown submits: `0`
- malformed submits: `0`
- Stratum Flip: `0`
- candidate: `0`

Operational interpretation at that point:

- keep `0.00025` unchanged
- continue passive observation
- only run candidate follow-up commands if a non-controlled real candidate appears

---

## 2026-05-09 Controlled Submit Follow-up

A real submitted candidate existed and was tracked through the follow-up path.

Observed candidate:

- job: `job-000000000000002c`
- submit time: `2026-05-09T11:09:53Z`
- block hash: `0000000108261e79c826a1bda1e5ea6e211be0b100cbfc16b8a047c0e102e253`

Latest recorded follow-up outcome:

- `chain-match-not-found`

Interpretation:

- the controlled submit path produced real submit evidence
- follow-up tooling was able to record a terminal chain lookup result
- the candidate was **not** found on-chain
- this must **not** be described as a confirmed block

Boundary:

- no payout implication
- no confirmed block-state transition
- no change to the default requirement that real submit remains explicitly gated

---

## 2026-05-11 One-Shot Submit Window

A one-shot real-submit window was run through the systemd-safe path.

Runtime guardrails:

- `PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true` only during the controlled window
- `PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1`
- real-submit budget remained one-shot

Stop trigger:

- `candidate-events` showed `submit-skipped-stale-prevblk`

Observed result:

- no new real submit attempt
- no new real submit sent
- no new real submit error
- budget was not consumed

Interpretation:

- stale-prevblk protection worked
- the pool did not send a candidate when the candidate prevhash was stale
- the real-submit guard avoided an unsafe daemon submission
- the service was returned to the default-off baseline after the window

Boundary:

- this was a safety-window validation
- it was not a block-found milestone
- it did not prove payout or round-state correctness

---

## 2026-05-12 Default-Off Safety Restoration

After reconnect, the running Stratum process still had real submit enabled even though `launch.env` already showed:

```bash
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=false
```

The mismatch was corrected through the systemd-owned safe path:

```bash
# Conceptual sequence recorded from operator notes
rewrite launch.env with the helper
sudo -n systemctl restart pepepow-pool-stratum.service
```

Service restart timestamp:

- `2026-05-12 14:57:35 UTC`

Final safety state:

- `real_submit_enabled: False`
- `PEPEPOW_ENABLE_REAL_SUBMITBLOCK=false`
- `PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1`
- `real_submit_attempt_count: 0`
- `real_submit_sent_count: 0`
- `real_submit_error_count: 0`

Final daemon-template readiness state:

- `drill_status: ready`
- `template_mode_effective: daemon-template`
- `template_fetch_status: ok`
- `template_daemon_rpc_reachable: True`

Interpretation:

- runtime submit state was safely restored to default-off
- launch configuration and running process state were brought back into alignment
- daemon-template readiness remained intact after restart

---

## Current Safe Baseline

As of the latest recorded checkpoint:

- daemon-template Stratum path is ready
- daemon RPC is reachable
- template fetch status is ok
- real submit is disabled
- one-shot real-submit budget remains configured but inactive
- no real-submit attempts are pending
- no real-submit errors are active

Current operator baseline:

```text
real_submit_enabled = False
real_submit_send_budget = 1
real_submit_attempt_count = 0
real_submit_sent_count = 0
real_submit_error_count = 0
template_mode_effective = daemon-template
template_fetch_status = ok
template_daemon_rpc_reachable = True
```

---

## Interpretation

The project has advanced beyond pure passive fixed-difficulty observation.

The post-2026-04-30 benchmark status is:

1. controlled real-submit evidence exists
2. chain follow-up can record `chain-match-not-found`
3. stale-prevblk guard can block unsafe submit attempts
4. real submit can be returned to default-off through the systemd-safe path
5. daemon-template readiness remains stable after restart

The most important safety conclusion is:

> Real submit must remain operator-controlled, explicitly gated, and default-off unless a deliberate one-shot drill is being performed.

---

## Remaining Boundary

Still not completed:

- confirmed real block found by the pool
- mature block lifecycle tracking
- round tracking
- payout accounting
- payout execution
- public candidate / block-state surfacing as production pool data

Do not claim the pool is payout-ready.

Do not reopen these closed lines unless new contradictory evidence appears:

- target math
- endian comparator
- header reconstruction
- merkle reconstruction
- submit-time job context alignment
- miner displayed-hash semantics

---

## Next Step

Keep the service on the safe default-off daemon-template baseline.

Only run the candidate follow-up path when a fresh non-controlled candidate appears:

```bash
./ops/scripts/live-stratum.sh candidate-followup 10 --record
./ops/scripts/live-stratum.sh candidate-outcomes 10
./ops/scripts/live-stratum.sh candidate-followup-events 10
```

If another real-submit drill is needed, use only the systemd-safe helper path and keep:

```bash
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1
```

Then immediately restore:

```bash
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=false
sudo -n systemctl restart pepepow-pool-stratum.service
```

---

## Suggested Commit

### Commit title

```text
Record May submit safety benchmark baseline
```

### Commit body

```text
Add post-2026-04-30 benchmark/progress notes for the PEPEPOW live Stratum path.

Document:
- controlled submit follow-up from 2026-05-09
- stale-prevblk guarded one-shot window from 2026-05-11
- default-off real-submit safety restoration from 2026-05-12

Keep the record scoped to operational benchmark evidence and preserve the
current boundary that real submit remains operator-controlled, default-off,
and not payout-ready.
```
