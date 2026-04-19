# 2026-04-18 Live Daemon-Template Candidate Wait State

## Scope

This note records the current live status while the daemon-template Stratum
service is connected to the real PEPEPOW chain, but the first real block
candidate has not yet been observed.

This is a waiting-state artifact only.

It does **not** claim:

- confirmed mining correctness to block-found level
- round tracking
- immature / confirmed / orphan handling
- payout readiness

## Confirmed Now

### Chain / mode

- live service is on the real PEPEPOW daemon-template path
- the service is not on the earlier synthetic-only path
- daemon-template status remains reachable / ready

### Share continuity

- accepted live shares continue arriving
- the external miner remains connected and active
- activity snapshot continues updating
- `Submit accepted` continues appearing in the live stratum log

### Candidate closure path

Controlled evidence already proved the candidate closure path works:

- `candidate-events`
- `candidate-followup --record`
- `candidate-outcomes`

Controlled closure already advanced correctly from:

- `submitted`

to:

- `chain-match-not-found`

### Error classification fix already validated

A real daemon `getblockheader` miss can surface as HTTP 500 with JSON-RPC
`code: -5`.

This path was already corrected so that a true block-not-found result advances
to:

- `no-match-found`
- `chain-match-not-found`

instead of being misclassified as `check-error`.

## Current Observed Limitation

No real candidate has yet been observed.

As of this note:

- `candidate-events` still contains only the controlled drill seed
- no non-controlled real candidate record has been appended
- `meetsBlockTarget=true` has not been observed in the live share path

This means the present gap is:

- **absence of a real block-target share**

and **not**:

- follow-up flow failure
- outcome consolidation failure
- daemon-template fetch failure
- daemon RPC reachability failure
- share-ingest failure

## Current Operational Meaning

Accepted shares are being observed on the real chain-connected path, but they
are still interpreted as ordinary pool shares unless they reach the block
target.

So the current state is:

- real chain
- real shares
- no real candidate yet

## Recommended Operator Action

Do not expand scope.

Keep the current live service unchanged and continue passive observation only.

When the first non-controlled candidate appears, run immediately:

```bash
./ops/scripts/live-stratum.sh candidate-followup 10 --record
./ops/scripts/live-stratum.sh candidate-outcomes 10
./ops/scripts/live-stratum.sh candidate-followup-events 10
```

## What Is Explicitly Deferred

Still deferred until after the first real candidate closure is observed:

- block lifecycle states
- round tracking
- immature / orphan logic
- payout accounting
- public candidate surfacing through API or frontend
- background retry / polling services

## Minimal Success Condition for the Next Step

The next milestone is reached only when:

1. a non-controlled real candidate appears
2. follow-up recording is executed
3. consolidated outcome is recorded for that real candidate
