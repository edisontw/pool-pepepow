# 2026-04-25 Live Fixed-Difficulty Share Outcome Baseline

## Scope

This note records the post-restart live fixed-difficulty share outcome baseline
after the pool-side miner-facing difficulty contradiction was closed.

This is a bounded live observation only. It does not claim a real block candidate
or payout readiness.

## Confirmed

- Active live session: `f470b0a6d5f16a03`
- Remote: `114.24.24.144:58006`
- Worker: `PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD.default`
- Miner-facing difficulty: `0.001`
- Difficulty emission reason: `authorize-fixed`
- Vardiff: disabled
- No `vardiff-retarget` emission observed

## Share Outcome

Bounded live status showed:

- Submits: `4074`
- Accepted shares: `68`
- Rejected shares: `4006`
- Dominant reject reason: `low-difficulty-share`

Rolling snapshot:

- 15m: `acceptedShares=68`, `rejectedShares=4006`
- 5m: `acceptedShares=27`, `rejectedShares=1412`
- 1m: `acceptedShares=5`, `rejectedShares=279`

## Candidate Status

`candidate-events 10` returned only the historical controlled drill entry from
`2026-04-18`.

No fresh non-controlled real candidate appeared in this bounded observation.

## Interpretation

The pool is not stuck at difficulty emission or share ingest.

At fixed `0.001`, the live session is producing both:

- expected low-difficulty rejects
- accepted valid pool shares

The current state is ordinary candidate-wait observation, not difficulty-emission
debug.

## Remaining Boundary

This note is bounded to the inspected live window. It does not make claims about
other miner-side log contexts, devfee endpoints, or external pools.