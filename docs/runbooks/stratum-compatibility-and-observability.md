# Stratum Compatibility and Observability Runbook (v2)

This runbook covers the normalized difficulty baseline, Stratum notify compatibility toggles, and live session observability.

## 1. Normalized Difficulty Baseline

The pool now enforces a minimum default difficulty of `1.0` for all daemon-template jobs. This prevents miners from being flooded with ultra-low difficulty synthetic work and ensures honest share validation.

### Confirming Effective Difficulty

Check the `effective_difficulty` field in `live-stratum.sh status`:

```bash
./ops/scripts/live-stratum.sh status | grep effective_difficulty
```

To override (higher values only recommended for live mining):
```bash
export PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY=2.0
./ops/scripts/live-stratum.sh restart
```

## 2. Stratum Notify Compatibility Toggle

Some miners (like `hoo_gpu`) require the `clean_jobs` field in `mining.notify` to be an integer (`0` or `1`) instead of a canonical JSON boolean (`true`/`false`).

### How to Toggle

Set `PEPEPOW_STRATUM_NOTIFY_CLEAN_JOBS_LEGACY` in your launch environment.

- **Standard (Default):** `false` (sends `true`/`false`)
- **Legacy/Miner-Compatible:** `true` (sends `0`/`1`)

Toggle command:
```bash
# Enable integer encoding
export PEPEPOW_STRATUM_NOTIFY_CLEAN_JOBS_LEGACY=true
./ops/scripts/live-stratum.sh restart
```

## 3. Session Rejection Observability

Live miner sessions can now be inspected for rejection reasons and job state without databases.

### Inspection Command

```bash
./ops/scripts/live-stratum.sh status
```

Example Output:
```text
active_sessions_count: 1
--- session:1234abcd5678efgh ---
  remote: 192.168.1.50
  worker: PEPE123.rig01
  submits: 50 (ok:48 / rej:2)
  diff: 1.0
  legacy_notify: true
  last_share: 2026-04-19T10:45:00Z
  rejections: unknown-job:1, stale-job:1
```

## 4. Rollback Instructions

If the new difficulty baseline or encoding causes issues:

1. Revert `PEPEPOW_STRATUM_NOTIFY_CLEAN_JOBS_LEGACY` to `false` (or unset it).
2. Restore `PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY` to previous value if needed (though `1.0` is the new recommended floor).
3. Restart: `./ops/scripts/live-stratum.sh restart`.
