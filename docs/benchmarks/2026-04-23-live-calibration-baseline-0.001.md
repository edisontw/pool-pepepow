# 2026-04-23 Live Calibration Baseline 0.001

## Scope

This note records the fixed-difficulty live calibration baseline for the
production-connected PEPEPOW Stratum path.

This is an operational calibration record, not a submit-path correctness
debugging record. Submit path correctness, target math, reconstruction,
job-context handling, and authoritative hash alignment remain closed unless
future contradictory evidence appears.

No code or runtime configuration changes were made for this milestone.

---

## Baseline Configuration

Runtime/config drift was checked before recording this note:

- `.runtime/live-stratum/launch.env` keeps
  `PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY=0.001`
- `.runtime/live-stratum/launch.env` keeps
  `PEPEPOW_POOL_CORE_STRATUM_VARDIFF_ENABLED=false`
- `.runtime/live-stratum/activity-snapshot.json` advertises difficulty
  `0.001`
- `apps/pool-core/config.py` keeps
  `MIN_HASHRATE_ASSUMED_SHARE_DIFFICULTY = 0.001`

The current recommended live baseline is fixed share difficulty `0.001` with
vardiff disabled.

---

## Observation Window

Longer bounded `0.001` live window:

- window: `2026-04-23T12:54:17Z` to `2026-04-23T13:18:19Z`
- accepted total: `96`
- rejected total: `6565`
- accepted ratio: `1.44%`
- reject reasons: `low-difficulty-share: 6565`
- `targetValidationStatusCounts`: `context-valid: 6661`
- `shareHashValidationStatusCounts`:
  `share-hash-valid: 96`, `low-difficulty-share: 6565`
- job status counts: `current: 6564`, `previous: 97`

The accepted density became operationally sufficient for continued live
observation at `0.001`. The reject mix stayed clean: low-difficulty-share only.
Stale, unknown, and malformed rejects did not materially appear.

Earlier accepted `0.001` checkpoint:

- accepted total: `75`
- rejected total: `5008`
- accepted ratio: `1.48%`

The extended window continued the same conclusion with more samples.

---

## Comparison Against 0.002

Prior bounded `0.002` live window:

- window: `2026-04-23T12:49:00Z` to `2026-04-23T12:53:44Z`
- accepted total: `10`
- rejected total: `1303`
- accepted ratio: `0.76%`
- reject reasons: `low-difficulty-share: 1303`
- `targetValidationStatusCounts`: `context-valid: 1313`
- `shareHashValidationStatusCounts`:
  `share-hash-valid: 10`, `low-difficulty-share: 1303`

Compared with `0.002`, fixed `0.001` produced materially denser accepted-share
evidence while preserving the same clean reject and target-validation profile.

---

## Validation

The `0.001` window preserved the narrowed live-calibration baseline:

- accepted shares continued, so this is no longer a zero-accepted-share path
- low-difficulty-share remained the dominant and only reject bucket
- target validation stayed `context-valid`
- stale, unknown, and malformed rejects did not materially appear
- authoritative hash alignment remained intact in submit evidence and was not
  reopened
- vardiff remained disabled

---

## Conclusion

Fixed live difficulty `0.001` is the current practical operating point for this
baseline.

Option B, a `0.0005` test, is deferred unless future evidence shows that
`0.001` becomes operationally sparse again.

---

## Next Step

Continue live observation at fixed difficulty `0.001` with vardiff disabled.
Do not change difficulty or reopen closed correctness lines unless new
contradictory evidence appears.

---

## Commit

### Commit title

`Record 0.001 live calibration baseline`

### Commit body

`Record the longer fixed-difficulty 0.001 live observation as the current
PEPEPOW pool calibration baseline.

Validation summary:
- compare 0.001 against the prior 0.002 bounded window
- preserve the narrowed closure around submit correctness and authoritative
  hash alignment
- keep vardiff disabled for the baseline
- defer 0.0005 unless 0.001 becomes operationally sparse again
- no code or config changes`
