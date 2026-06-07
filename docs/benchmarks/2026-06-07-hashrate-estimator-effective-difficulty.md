# 2026-06-07 Hashrate Estimator Effective Difficulty Fix

## Summary

This document records the final corrected convention for the PEPEPOW pool share-derived hashrate estimator.

The estimator was debugged against three independent miner/pool observations:

* `pool.pepepow.net`
* Mining4People
* Foztor's pool

The final conclusion is:

```text
Estimated hashrate must use accepted share effective difficulty, not Stratum wire difficulty.
```

Correct convention:

```text
estimated_hashrate =
sum(accepted_share_effective_difficulty * 2^32) / window_seconds
```

Do not use:

```text
accepted_share_rate_per_second * wire_difficulty * 2^32
```

Do not multiply estimator difficulty by `65536`.

---

## Background

PEPEPOW Stratum difficulty appears in miner logs in two forms:

```text
stratum difficulty 98.304 (0.00150000)
```

Interpretation:

```text
wire difficulty      = 98.304
effective difficulty = 0.00150000
scale                = 65536
wire = effective * scale
```

The wire difficulty is used for Stratum protocol / miner display compatibility.

The hashrate estimator must use the effective difficulty because accepted share frequency aligns with miner local hashrate only under the effective-difficulty convention.

---

## Final Estimator Convention

Use:

```text
estimated_hashrate =
sum(accepted_share_effective_difficulty * 2^32) / window_seconds
```

Equivalent form when all accepted shares in the window use the same difficulty:

```text
estimated_hashrate =
accepted_share_count / window_seconds
* effective_share_difficulty
* 2^32
```

The estimator is share-derived and window-based. It is not miner-reported local hashrate.

---

## What Was Corrected

### 1. `/1000` Was Removed

Previous bad convention:

```text
HASHES_PER_SHARE = 2^32 / 1000
```

Correct convention:

```text
HASHES_PER_SHARE = 2^32
```

The estimator output is already in H/s. Dividing by `1000` incorrectly under-reports by 1000x.

This correction remains valid.

---

### 2. Wire Difficulty Was Removed from Estimator

A temporary incorrect fix used:

```text
accepted_share_rate_per_second * wire_difficulty * 2^32
```

This was wrong because wire difficulty already includes the PEPEW scale factor:

```text
wire_difficulty = effective_difficulty * 65536
```

Using wire difficulty in the estimator over-reports by 65536x.

Correct estimator difficulty:

```text
effective_difficulty
```

not:

```text
wire_difficulty
```

---

### 3. Live ShareEvent Difficulty Source Was Fixed

The remaining live mismatch came from `ShareEvent` construction during live Stratum submit handling.

Persisted share logs already contained the correct effective difficulty:

```json
"difficulty": 0.0015
```

and diagnostic data also contained:

```json
"shareHashDiagnostic": {
  "shareDifficultyUsed": 0.0015
}
```

However, the live ingress path instantiated `ShareEvent(...)` without passing the difficulty field. This caused:

```text
difficulty = None
```

Then `ActivityEngine` fell back to:

```text
assumedShareDifficulty = 0.00025
```

This made the live estimator under-report when actual accepted shares were submitted at effective difficulty `0.0015`.

Correct live behavior:

```text
ShareEvent difficulty should be populated from the session's current effective difficulty.
```

The fix passes:

```python
difficulty=state.current_difficulty or self._synthetic_difficulty()
```

when constructing `ShareEvent` for accepted submit handling.

---

## Numerical Evidence

### Miner Observation

`pool.pepepow.net` miner log showed:

```text
stratum difficulty 98.304 (0.00150000)
```

RTX 2060 miner local speed:

```text
~825–925 KH/s
```

Accepted shares example:

```text
16 accepted shares / ~117.37 seconds
```

Using effective difficulty:

```text
16 / 117.37 * 0.0015 * 2^32
≈ 878 KH/s
```

This matches the miner local hashrate range.

Using wire difficulty:

```text
16 / 117.37 * 98.304 * 2^32
≈ 57.6 GH/s
```

This is wrong by 65536x.

---

## Live Verification After Final Fix

Before final live difficulty-source fix:

```text
36 accepted shares / 300s * 0.00025 * 2^32
≈ 129 KH/s
```

This was too low versus miner local speed.

After passing the real share effective difficulty into `ShareEvent`:

```text
43 accepted shares / 300s * 0.0015 * 2^32
≈ 923 KH/s
```

Live API result:

```text
poolHashrate ≈ 923 KH/s
```

This matches the miner local speed range:

```text
~825–925 KH/s
```

---

## Correctness Rules Going Forward

Do not change these without new contradictory evidence:

### Estimator Formula

```text
sum(accepted_share_effective_difficulty * 2^32) / window_seconds
```

### Difficulty Source Priority

For accepted shares:

1. Use the share event's actual effective difficulty.
2. If unavailable, use a safe fallback `assumedShareDifficulty`.
3. Rejected shares must not contribute to hashrate.

### Do Not Use

```text
wire_difficulty
effective_difficulty * 65536
2^32 / 1000
submitted share count including rejects
network hashrate
miner display "Pool:" field
```

---

## Important Distinction

The frontend/API pool hashrate is:

```text
accepted-share-derived estimated hashrate
```

It is not:

```text
miner-reported local hashrate
network hashrate
blockchain-verified hashrate
```

Short windows may fluctuate because share discovery is probabilistic.

The correct validation is not exact second-by-second equality, but order-of-magnitude alignment with:

```text
accepted share frequency
effective difficulty
miner local hashrate
```

---

## Files Involved

Main corrected files:

```text
apps/pool-core/activity_engine.py
apps/pool-core/stratum_ingress.py
apps/pool-core/producer.py
tests/test_stratum_ingress.py
```

Primary live fix:

```text
apps/pool-core/stratum_ingress.py
```

The key live-path correction was to ensure `ShareEvent` receives the actual effective difficulty at submit time.

---

## Verification Commands

Focused tests:

```bash
PYTHONPATH=apps/api:apps/pool-core python3 -m unittest tests.test_stratum_ingress tests.test_api_endpoints
bash -n ops/scripts/*.sh
```

Live API check:

```bash
curl -s http://127.0.0.1:8080/api/pool/summary | jq '{
  poolHashrate,
  hashrate,
  assumedShareDifficulty,
  hashratePolicy,
  activeMiners,
  activeWorkers,
  rolling
}'
```

Bounded accepted-share check:

```bash
tail -n 300 .runtime/live-stratum/share-events.jsonl \
  | jq -r 'select(.accepted == true) | [.timestamp,.worker,.difficulty,.shareHashDiagnostic.shareDifficultyUsed] | @tsv' \
  | tail -n 80
```

Manual expected value:

```text
expected =
sum(accepted_share_effective_difficulty * 2^32) / window_seconds
```

For same-difficulty shares:

```text
expected =
accepted_count / window_seconds * effective_difficulty * 2^32
```

---

## Final Status

Status:

```text
Fixed and live-verified
```

Final live result:

```text
poolHashrate ≈ 923 KH/s
```

Interpretation:

```text
The estimator now aligns with miner local hashrate, accepted share frequency,
and effective difficulty.
```

No further estimator patch is recommended unless new evidence shows mismatch between:

```text
accepted share timestamps
accepted share effective difficulty
window duration
API-reported poolHashrate
```
