# Snapshot Pipeline Runbook

## Scope

This runbook covers:

- the daemon-aware runtime snapshot producer
- fallback snapshot behavior
- the additive activity snapshot overlay path
- API source priority and degradation behavior

It does not cover future validated mining, block submission, or payouts.

---

## Snapshot Inputs

Current snapshot sources:

1. runtime snapshot produced by `apps/pool-core/producer.py`
2. fallback snapshot in `apps/api/data/mock/pool-snapshot.json`
3. additive activity snapshot produced by `apps/pool-core/stratum_ingress.py`

Current file paths:

- runtime snapshot: `/var/lib/pepepow-pool/pool-snapshot.json`
- fallback snapshot: repository mock file
- activity snapshot: `/var/lib/pepepow-pool/activity-snapshot.json`

---

## Runtime Snapshot Producer

The producer is daemon-aware and reads low-cost RPC data only.

Run once:

```bash
cd /opt/pepepow-pool/apps/pool-core
python3 producer.py --once
```

Expected result:

- snapshot file appears at `/var/lib/pepepow-pool/pool-snapshot.json`
- file contains `meta.blockFeedKind = "observed-network-blocks"`
- `meta.chainState` is `reindexing`, `syncing`, or `synced`
- chain fields come from daemon RPC only

---

## Activity Sources

The current stack supports two activity inputs:

### 1. Producer Local JSONL Ingest

The producer can still read a local JSONL share log and merge low-cost activity
metadata into the runtime snapshot path.

### 2. Stratum Ingress Activity Snapshot

The Stratum ingress service writes:

- `share-events.jsonl`
- rotated `share-events.<first>-<last>.jsonl`
- `activity-snapshot.json`

This path is daemon-independent and is the current live share-ingest path.
Its current job mode is synthetic/fake work for protocol compatibility only.

---

## API Source Priority

Base snapshot priority remains:

1. runtime snapshot
2. fallback snapshot

After the base snapshot is selected, the API applies the optional activity
snapshot overlay.

The overlay updates activity-owned fields only, including:

- miner records
- pool hashrate derived from shares
- active miners
- active workers
- worker distribution
- activity metadata

Chain fields still come from the runtime or fallback base snapshot.

---

## Trust and Presentation Rules

- share-derived fields are derived from shares
- share-derived fields are not blockchain verified
- estimated hashrate is a rough estimate using assumed share difficulty
- activity overlay does not imply validated mining correctness
- synthetic job mode does not imply real template retrieval or real share validation

---

## Validate API

```bash
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/pool/summary
curl http://127.0.0.1:8080/api/network/summary
curl http://127.0.0.1:8080/api/blocks
curl http://127.0.0.1:8080/api/miner/YOUR_WALLET
```

Look for:

- `snapshotSource = runtime` or `fallback`
- `activityMode = stratum-share-ingest` when Stratum overlay is active
- `activityDerivedFromShares = true`
- `blockchainVerified = false`
- `activityDataStatus = empty|live|stale`
- `hashratePolicy = share-rate-assumed-diff`
- synthetic/fake work remains non-validated and not blockchain verified

---

## Reindex-State Validation Boundary

Acceptable during `-reindex`:

- RPC authentication and connectivity
- producer runtime snapshot writes
- API runtime snapshot preference
- stale/degraded/fallback behavior
- Stratum ingress and activity overlay behavior

Not acceptable as final full-pool acceptance during `-reindex`:

- final chain height
- final difficulty
- latest block stability
- validated share correctness
- block submission correctness

---

## Failure Behavior

### If Daemon RPC Becomes Unreachable

- producer logs warnings and keeps the last good runtime snapshot file
- API keeps serving runtime snapshot until it becomes stale
- if runtime snapshot is missing or invalid, API serves fallback mock snapshot
- activity overlay can still update if `activity-snapshot.json` remains healthy
- `/api/health` reports degraded chain metadata

### If Activity Snapshot Becomes Unreadable

- API still serves runtime or fallback base snapshot
- activity-derived fields stop updating
- `/api/health` reports degraded activity metadata

### If Local Share Log Becomes Unreadable

- Stratum ingress logs write errors
- activity snapshot may stop advancing
- API serves the last valid activity overlay until it is replaced or removed

### If Rotation Retention Trims Replay Tail

- restart still seeds lifetime totals from `activity-snapshot.json`
- rolling windows are rebuilt only from the retained tail
- `warningCount` may rise when retained logs no longer fully cover the replay floor

---

## Service Control

```bash
systemctl restart pepepow-pool-core.service
systemctl restart pepepow-pool-stratum.service
systemctl restart pepepow-pool-api.service
systemctl status pepepow-pool-core.service --no-pager
systemctl status pepepow-pool-stratum.service --no-pager
systemctl status pepepow-pool-api.service --no-pager
```

Logs:

```bash
journalctl -u pepepow-pool-core.service -n 100 --no-pager
journalctl -u pepepow-pool-stratum.service -n 100 --no-pager
journalctl -u pepepow-pool-api.service -n 100 --no-pager
```

---

## Rollback

- stop `pepepow-pool-stratum.service` if share ingest changes need rollback
- stop `pepepow-pool-core.service` if runtime snapshot changes need rollback
- restore env files if snapshot or activity paths were changed
- restore daemon config backup if RPC config was changed
- restart affected services
- re-run API health checks

---

## Security Notes

- keep daemon RPC on `127.0.0.1` or private subnet only
- do not expose daemon RPC publicly
- do not expose raw share logs publicly
- do not expose the internal activity snapshot as a public API
- if Redis is introduced later, do not expose it publicly

---

## Benchmarks

Reference benchmark results for the current Stratum ingest path:

- [2026-04-13-stratum-ingress.md](/home/ubuntu/pool-pepepow/docs/benchmarks/2026-04-13-stratum-ingress.md)
