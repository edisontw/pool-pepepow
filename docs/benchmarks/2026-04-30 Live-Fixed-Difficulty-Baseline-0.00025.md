# 2026-04-30 Live Fixed Difficulty Baseline 0.00025

## Summary
The live PEPEPOW Stratum baseline is now fixed at effective share difficulty `0.00025`, corresponding to miner wire difficulty `16.384` with PEPEW scale `65536`.

This setting replaced the earlier `0.000075` operational baseline because it materially reduced miner-side Stratum Flip noise while preserving accepted-share flow. A direct M4P-aligned trial at `0.00390625 / wire 256` was too sparse for the current observation phase.

## Current Live Baseline
- effectiveShareDifficulty: `0.00025`
- minerWireDifficulty: `16.384`
- difficultyScale: `65536`
- vardiffEnabled: `false`
- low-diff share-event throttle: every `10`
- clean rollover behavior: `mining.set_difficulty` before `mining.notify`

## Fresh Miner Window
Observation window:
- `2026-04-30T15:26:04Z` to `2026-04-30T15:29:44Z`

Miner session:
- session: `b83b967ed717dcdd`
- remote: `122.116.62.52:53630`

Results:
- submits: `176`
- accepted: `6`
- rejected: `170`
- reject reason: `low-difficulty-share` only
- stale: `0`
- unknown: `0`
- malformed: `0`
- Stratum Flip: `0`
- candidate: `0`

Accepted spacing:
- min: `2s`
- median: `33s`
- average: `38.2s`
- max: `91s`

## Interpretation
The `0.00025` baseline restores accepted-share flow while avoiding the excessive miner-side Flip chatter seen at `0.000075`.

No evidence currently supports further difficulty changes or reopening target math, endian comparator, merkle, submitblock, candidate prep, or miner displayed-hash semantics.

## Recommendation
Keep `0.00025` unchanged and continue passive observation. Only run candidate follow-up commands if a non-controlled real candidate appears.