# Real Candidate Watch and Follow-Up Runbook

## Purpose

This runbook defines the minimum operator workflow while the live daemon-template
Stratum service is running on the real PEPEPOW chain, but no real block
candidate has yet been observed.

This is intentionally small-scope.

It does **not** introduce:

- round tracking
- immature / confirmed / orphan lifecycle
- payout handling
- API / frontend candidate surfacing
- background retry workers

It exists only to help operators detect the first real candidate and execute the
already-implemented follow-up / outcome closure path.

## Current Interpretation Boundary

The current live service is connected to the **real PEPEPOW chain** through the
daemon-template path.

However, the presence of accepted shares does **not** imply a block candidate.

A real candidate exists only when a submitted share reaches the block target and
causes the pool to emit a real candidate record.

Operationally, the first useful signal is one of:

- a new non-controlled entry in `candidate-events.jsonl`
- a share event with `meetsBlockTarget=true`

Until then, accepted shares are still interpreted as normal pool shares only.

## Runtime Files

- `.runtime/live-stratum/share-events.jsonl`
- `.runtime/live-stratum/candidate-events.jsonl`
- `.runtime/live-stratum/candidate-followup-events.jsonl`
- `.runtime/live-stratum/candidate-outcome-events.jsonl`
- `.runtime/live-stratum/activity-snapshot.json`
- `.runtime/live-stratum/stratum.log`

## Quick Status Checks

### Service / daemon-template status

```bash
./ops/scripts/live-stratum.sh drill-status
```

Expected useful fields:

- `drill_status: ready`
- `template_mode_effective: daemon-template`
- `template_fetch_status: ok`
- `template_daemon_rpc_reachable: True`

### Latest candidate records

```bash
./ops/scripts/live-stratum.sh candidate-events 10
```

### Latest consolidated outcomes

```bash
./ops/scripts/live-stratum.sh candidate-outcomes 10
```

### Latest recorded follow-up events

```bash
./ops/scripts/live-stratum.sh candidate-followup-events 10
```

## How to Recognize the First Real Candidate

A real candidate is present only when `candidate-events` shows a new entry that
is **not** the known controlled drill seed.

Treat the following as controlled evidence and not a real candidate:

- `jobId` containing `controlled-drill`
- `wallet = controlled-drill`
- `worker = controlled-drill`

A real candidate should have:

- a fresh timestamp
- a non-controlled `jobId`
- a real miner wallet / worker
- a real `candidateBlockHash`

Optional lower-level confirmation:

```bash
grep -n '"meetsBlockTarget":true' .runtime/live-stratum/share-events.jsonl | tail
```

If this returns no lines, no real candidate has yet been observed.

## Trigger Procedure When a Real Candidate Appears

Run immediately:

```bash
./ops/scripts/live-stratum.sh candidate-followup 10 --record
./ops/scripts/live-stratum.sh candidate-outcomes 10
./ops/scripts/live-stratum.sh candidate-followup-events 10
```

This should append the follow-up event and advance the consolidated outcome from:

- `submitted`

to one of:

- `chain-match-found`
- `chain-match-not-found`
- `check-error`

## Interpretation of Follow-Up Results

### `chain-match-found`

The candidate block hash was found on the local chain view.

### `chain-match-not-found`

The candidate block hash was not found on the local chain view.

This does **not** yet imply orphan logic, round accounting, or payout logic.

### `check-error`

The follow-up check itself failed and requires operator inspection.

## What Not to Do While Waiting

Do **not** expand scope into:

- round accounting
- immature / confirmed / orphan states
- payment flow
- public API additions
- frontend additions
- permanent background polling services
- additional status taxonomy

The current missing piece is the first real candidate, not another feature
layer.

## Recommended Passive Watch Commands

### Candidate watch

```bash
watch -n 10 './ops/scripts/live-stratum.sh candidate-events 10'
```

### Service health watch

```bash
watch -n 10 './ops/scripts/live-stratum.sh drill-status'
```

### Block-target watch

```bash
watch -n 10 "grep -c '\"meetsBlockTarget\":true' .runtime/live-stratum/share-events.jsonl"
```

## Exit Condition for This Runbook

This runbook remains the correct operator procedure until one of these occurs:

1. the first real candidate is observed and follow-up closure is recorded
2. the live path is intentionally redesigned
3. block lifecycle tracking is intentionally started in a later milestone
