# 2026-04-19 Live Difficulty Floor Correction

## Scope

This artifact records the narrowed diagnosis and minimum corrective patch for
an abnormal live daemon-template difficulty / hashrate path observed on the
current production-connected PEPEPOW Stratum service.

The purpose of this change is not to introduce vardiff or redesign the mining
path. It only prevents the most pathological live configuration case where the
effective share difficulty can fall to `1e-08`, causing share-rate / hashrate
semantics to become misleading.

This artifact does not claim that the pool is now a full validating production
pool, and it does not add round tracking, block-state tracking, or payouts.

---

## Observed Problem

During extended live observation on the daemon-template path:

- accepted shares continued normally
- no real live `candidate-events` were recorded
- only the previously seeded `controlled-drill` candidate remained present
- the external miner reported unrealistic pool-side speed ranges, including
  large jumps into `MH/s`
- the same miner on another live PEPEPOW pool remained around
  `640–730 KH/s`
- local live logs showed miner difficulty values including `0.01` and
  `1e-08`

This made the accepted-share rate and displayed hashrate unsuitable for judging
how close the live path was to producing a real block candidate.

---

## Diagnosis

The current live path uses a single configuration value for three separate
purposes:

1. miner-facing `mining.set_difficulty`
2. pool-side share-target derivation
3. share-derived hashrate estimation

The narrowed findings were:

- after authorize, `mining.set_difficulty` is sent directly from
  `_synthetic_difficulty()`
- `_synthetic_difficulty()` returns
  `config.hashrate_assumed_share_difficulty` directly
- the same value is used again for local share-target comparison
- the same value is also used by the hashrate estimator

This means `hashrate_assumed_share_difficulty` is currently a single shared
control value for:

- miner difficulty semantics
- share-validation semantics
- hashrate estimation semantics

No separate live vardiff implementation was found in the current
`apps/pool-core` path for this flow.

---

## Why `1e-08` Was Pathological

The live config loader previously allowed the floor for
`PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY` to clamp as low as
`0.00000001`.

That value was too low for the live daemon-template path.

Approximate work represented by one accepted share at each difficulty:

- `diff = 1e-08` -> about `42.95` hashes
- `diff = 0.01` -> about `42,949,672.96` hashes

That is a `1,000,000x` difference.

So when the live path fell to `1e-08`:

- shares became extremely easy
- accepted-share density became artificially high
- pool-side share-derived hashrate became misleading
- miner-side displayed pool speed could also become misleading
- “many accepted shares” no longer implied meaningful progress toward a real
  block candidate

In practical terms, this created a share storm rather than useful candidate
evidence.

---

## External Comparison Note

Comparison against another live PEPEPOW pool showed that difficulty changes by
themselves are not automatically suspicious.

Observed external examples included transitions such as:

- `0.01`
- `161.154`
- `204.145`

while the miner still reported a plausible steady range around
`640–730 KH/s`.

This supports the narrower conclusion that the core issue was not merely
“difficulty changed,” but that the local live path could fall to the
pathologically low `1e-08` floor.

---

## Minimum Corrective Patch

A minimum patch was applied to prevent the live config floor from falling to
`1e-08`.

Changed file:

- `apps/pool-core/config.py`

Behavior change:

- the minimum clamp for
  `PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY`
  was raised from `0.00000001` to `0.01`

This is intentionally a narrow corrective patch.

It does not yet separate:

- miner difficulty
- pool share target difficulty
- hashrate assumed share difficulty

It only removes the most pathological live floor so that the current path is
less misleading during continued candidate observation.

---

## Test Coverage Added

A focused regression test was added to ensure the config loader does not clamp
the live assumed share difficulty back down to `1e-08`.

Changed file:

- `tests/test_stratum_ingress.py`

Targeted test intent:

- `load_config()` must clamp
  `PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY`
  to the new live floor rather than allowing `1e-08`

Additional existing authorize-path coverage was also re-run to confirm
difficulty push behavior remained intact.

---

## Verification

Targeted verification commands:

```bash
python3 -m unittest tests.test_stratum_ingress.StratumIngressTests.test_load_config_clamps_hashrate_assumed_share_difficulty_to_pool_floor
python3 -m unittest tests.test_stratum_ingress.StratumIngressTests.test_authorize_pushes_synthetic_difficulty_and_notify