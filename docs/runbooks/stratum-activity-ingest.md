# Stratum Activity Ingest Runbook

## Scope

This runbook covers the daemon-independent Stratum ingress service, the
share-event JSONL log, the activity snapshot writer, and the API overlay path.

It does not cover:

- validated share handling
- real block templates
- candidate block handling or block submission
- payouts

Current synthetic accepted shares in this runbook are still non-validated and
not blockchain verified.

---

## Service Layout

Current services involved in share ingest:

- `pepepow-pool-stratum.service`
  - runs `apps/pool-core/stratum_ingress.py`
  - accepts `mining.subscribe`
  - returns a standard Stratum v1 subscription tuple list plus extranonce fields
  - accepts `mining.extranonce.subscribe` as a no-op compatibility method
  - accepts `mining.authorize`
  - pushes synthetic `mining.set_difficulty`
  - pushes synthetic `mining.notify`
  - accepts `mining.submit`
  - appends shares to JSONL
  - rotates JSONL by size and retains bounded rotated files
  - writes `activity-snapshot.json`
- `pepepow-pool-api.service`
  - reads runtime snapshot or fallback snapshot
  - overlays activity fields from `activity-snapshot.json`

Optional supporting service:

- `pepepow-pool-core.service`
  - writes daemon-aware `pool-snapshot.json`

---

## Required Environment Variables

From `ops/env/pool-core.env`:

- `PEPEPOW_POOL_CORE_STRATUM_BIND_HOST`
- `PEPEPOW_POOL_CORE_STRATUM_BIND_PORT`
- `PEPEPOW_POOL_CORE_STRATUM_HOST`
- `PEPEPOW_POOL_CORE_STRATUM_PORT`
- `PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH`
- `PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_OUTPUT`
- `PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS`
- `PEPEPOW_POOL_CORE_STRATUM_QUEUE_MAXSIZE`
- `PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY`
- `PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS`
- `PEPEPOW_POOL_CORE_ACTIVITY_LOG_ROTATE_BYTES`
- `PEPEPOW_POOL_CORE_ACTIVITY_LOG_RETENTION_FILES`

From `ops/env/api.env`:

- `PEPEPOW_POOL_API_RUNTIME_SNAPSHOT_PATH`
- `PEPEPOW_POOL_API_FALLBACK_SNAPSHOT_PATH`
- `PEPEPOW_POOL_API_ACTIVITY_SNAPSHOT_PATH`

---

## Expected Files

Current runtime artifacts:

- `/var/lib/pepepow-pool/share-events.jsonl`
- `/var/lib/pepepow-pool/share-events.<first>-<last>.jsonl`
- `/var/lib/pepepow-pool/activity-snapshot.json`
- `/var/lib/pepepow-pool/pool-snapshot.json`

Notes:

- `share-events.jsonl` is the append-only ingest log
- rotated `share-events.<first>-<last>.jsonl` files are bounded retained history
- `activity-snapshot.json` is internal and additive
- `pool-snapshot.json` remains the chain/base snapshot owned by the producer
- restart recovery is snapshot-first and only replays retained rolling-tail shares

---

## Start / Stop / Restart

Start:

```bash
systemctl enable --now pepepow-pool-stratum.service
systemctl enable --now pepepow-pool-api.service
```

Optional runtime snapshot producer:

```bash
systemctl enable --now pepepow-pool-core.service
```

Status:

```bash
systemctl status pepepow-pool-stratum.service --no-pager
systemctl status pepepow-pool-api.service --no-pager
```

Restart:

```bash
systemctl restart pepepow-pool-stratum.service
systemctl restart pepepow-pool-api.service
```

Logs:

```bash
journalctl -u pepepow-pool-stratum.service -n 100 --no-pager
journalctl -u pepepow-pool-api.service -n 100 --no-pager
```

---

## Verification

## 1. TCP Connect

Verify the Stratum port is listening:

```bash
ss -ltnp | grep 3333
```

Replace `3333` with the configured bind port if different.

## 2. Submit One Share

Use the built-in generator for a low-rate smoke test:

```bash
cd /opt/pepepow-pool
python3 apps/pool-core/tools/generate_shares.py \
  --host 127.0.0.1 \
  --port 3333 \
  --rate 1 \
  --duration 3 \
  --connections 1 \
  --activity-log-path /var/lib/pepepow-pool/share-events.jsonl \
  --activity-snapshot-path /var/lib/pepepow-pool/activity-snapshot.json \
  --api-base-url http://127.0.0.1:8080/api
```

## 3. Check JSONL Append

```bash
tail -n 3 /var/lib/pepepow-pool/share-events.jsonl
```

Look for:

- `source = "stratum"`
- `wallet`
- `worker`
- `sequence`
- `jobId`
- `syntheticWork = true`
- `shareValidationMode = "none"`
- `submit`

## 4. Check API Health

```bash
curl http://127.0.0.1:8080/api/health
```

Look for:

- `activityMode = "stratum-share-ingest"`
- `activityDerivedFromShares = true`
- `blockchainVerified = false`
- `activityDataStatus = live`

Current Stratum job mode is synthetic/fake work. It is non-validated, not
blockchain verified, and does not use real daemon templates yet.

## 5. Check Pool Summary

```bash
curl http://127.0.0.1:8080/api/pool/summary
```

Look for:

- `poolHashrate`
- `activeMiners`
- `activeWorkers`
- `workerDistribution`
- `hashratePolicy = "share-rate-assumed-diff"`

These fields are derived from shares and not blockchain verified.

## 6. Check Miner View

```bash
curl http://127.0.0.1:8080/api/miner/YOUR_WALLET
```

Look for:

- `summary.shareCount`
- `summary.rolling`
- worker-level `shareCount`
- worker-level `rolling`
- `lastShareAt`

---

## External Synthetic Preflight

Use the dedicated preflight script when you want a reproducible external miner
smoke without daemon/template dependencies.

Recommended external smoke command:

```bash
PEPEPOW_PREFLIGHT_PUBLIC_HOST=192.9.160.179 \
PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY=0.000001 \
/home/ubuntu/pool-pepepow/ops/scripts/run-stratum-preflight.sh
```

Notes:

- default preflight port is `39333/tcp`
- the script binds to `0.0.0.0` by default unless overridden
- the default synthetic notify interval is `5` seconds
- external smoke should lower `PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY` from the
  script default when the goal is accepted synthetic shares from a real miner

Confirm the pool side before testing externally:

```bash
ss -ltnp | grep 39333
pgrep -af run-stratum-preflight
tail -n 100 /tmp/pepepow-preflight/stratum.log
```

---

## Firewall And Exposure Prerequisites

For external testing, both cloud-side and host-side exposure must be correct.

Required checks:

- OCI ingress rules must allow the synthetic Stratum port, for example
  `39333/tcp`
- host firewall rules must also allow the same port
- Oracle Ubuntu images may carry default `iptables` rules even when OCI ingress
  is already open

Treat this as an ops exposure problem first, not as a miner protocol problem.
If OCI ingress is open but the miner still cannot connect, inspect host
firewall policy before debugging Stratum compatibility.

Recommended checks:

```bash
sudo iptables -S
sudo nft list ruleset
ss -ltnp | grep 39333
nc -vz 127.0.0.1 39333
```

From an external host:

```bash
nc -vz 192.9.160.179 39333
```

---

## External Miner Smoke Procedure

1. Start the synthetic preflight pool with the external endpoint and lowered
   synthetic difficulty.
2. Confirm the pool is listening on `39333/tcp`.
3. Confirm OCI ingress and host firewall both allow the port.
4. Start the external miner against the public endpoint.
5. Watch `/tmp/pepepow-preflight/stratum.log` and
   `/tmp/pepepow-preflight/share-events.jsonl`.
6. Confirm accepted synthetic submits appear with `syntheticWork = true`,
   `shareValidationMode = "none"`, and `blockchainVerified = false`.

External miner example:

```bash
./hoo_gpu -o stratum+tcp://192.9.160.179:39333 -u <wallet>.<worker> -gpu-id 0 -p x --pepepow
```

Expected behavior in this phase:

- connection succeeds to the synthetic endpoint
- the miner receives synthetic `mining.set_difficulty`
- the miner receives repeated synthetic `mining.notify`
- job rollover occurs on later notify cycles
- accepted synthetic shares may appear once synthetic difficulty is low enough

---

## If Connected But No Shares

If the miner connects but no shares appear in
`/tmp/pepepow-preflight/share-events.jsonl`, first lower
`PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY`.

Start with:

- `PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY=0.000001`

Do not assume protocol incompatibility first. In the verified external GPU
smoke, the deciding factor for accepted submits was lowering synthetic
difficulty, not redesigning the Stratum protocol.

---

## Generate Formal Smoke Report

After the run, generate the standard smoke summary from retained artifacts:

```bash
python3 /home/ubuntu/pool-pepepow/ops/scripts/stratum_smoke_report.py \
  --share-log /tmp/pepepow-preflight/share-events.jsonl \
  --activity-snapshot /tmp/pepepow-preflight/activity-snapshot.json \
  --pool-log /tmp/pepepow-preflight/stratum.log \
  --miner-name 'HTN GPU Miner' \
  --miner-version 'hoo_gpu 1.4.7' \
  --source-provenance 'https://pepepow.org/mining/ ; https://htn.foztor.net/hoo_gpu.tar.gz' \
  --build-method 'wget -c https://htn.foztor.net/hoo_gpu.tar.gz -O - | tar -xz' \
  --environment-platform 'x86_64 Ubuntu + NVIDIA GPU' \
  --pool-command 'PEPEPOW_PREFLIGHT_PUBLIC_HOST=192.9.160.179 PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY=0.000001 /home/ubuntu/pool-pepepow/ops/scripts/run-stratum-preflight.sh' \
  --miner-command './hoo_gpu -o stratum+tcp://192.9.160.179:39333 -u PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD -gpu-id 0 -p x --pepepow'
```

For the formally recorded external GPU smoke, see:

- [2026-04-14-external-gpu-stratum-smoke.md](/home/ubuntu/pool-pepepow/docs/benchmarks/2026-04-14-external-gpu-stratum-smoke.md)

---

## Current Verified Now

- external synthetic Stratum connectivity
- synthetic notify/job rollover compatibility
- accepted synthetic shares from a real external GPU miner

---

## Not Yet Implemented

- real daemon-backed work or template retrieval
- real share validation
- candidate block detection
- `submitblock`
- payout / round / balance tracking

---

## Failure Modes

### Activity Snapshot Unreadable

Symptoms:

- API still serves runtime or fallback snapshot
- activity fields stop updating
- `/api/health` shows degraded or stale activity metadata

Checks:

- `journalctl -u pepepow-pool-stratum.service -n 100 --no-pager`
- file permissions on `/var/lib/pepepow-pool`

### JSONL Append Blocked

Symptoms:

- Stratum service logs write errors
- `share-events.jsonl` stops growing
- activity snapshot sequence stops increasing

Checks:

- disk space
- file permissions
- journald errors

### Replay Coverage Trimmed By Retention

Symptoms:

- restart succeeds but `warningCount` increases
- rolling `1m` / `5m` / `15m` share counts may restart lower than before
- lifetime accepted/rejected totals remain anchored by `activity-snapshot.json`

Checks:

- retained `share-events.<first>-<last>.jsonl` files
- `windowReplaySequenceFloor` in `activity-snapshot.json`
- configured rotate bytes and retention file count

### API Fallback Without Activity Overlay

Symptoms:

- `/api/health` returns `snapshotSource = fallback`
- miner activity fields remain empty or old

Checks:

- `PEPEPOW_POOL_API_ACTIVITY_SNAPSHOT_PATH`
- existence and JSON validity of `activity-snapshot.json`
- `journalctl -u pepepow-pool-api.service -n 100 --no-pager`

---

## Stress Test

Example load runs:

```bash
python3 apps/pool-core/tools/generate_shares.py \
  --host 127.0.0.1 \
  --port 3333 \
  --rate 100 \
  --duration 60 \
  --connections 10 \
  --activity-log-path /var/lib/pepepow-pool/share-events.jsonl \
  --activity-snapshot-path /var/lib/pepepow-pool/activity-snapshot.json \
  --api-base-url http://127.0.0.1:8080/api
```

```bash
python3 apps/pool-core/tools/generate_shares.py \
  --host 127.0.0.1 \
  --port 3333 \
  --rate 500 \
  --duration 60 \
  --connections 25 \
  --activity-log-path /var/lib/pepepow-pool/share-events.jsonl \
  --activity-snapshot-path /var/lib/pepepow-pool/activity-snapshot.json \
  --api-base-url http://127.0.0.1:8080/api
```

```bash
python3 apps/pool-core/tools/generate_shares.py \
  --host 127.0.0.1 \
  --port 3333 \
  --rate 1000 \
  --duration 60 \
  --connections 50 \
  --activity-log-path /var/lib/pepepow-pool/share-events.jsonl \
  --activity-snapshot-path /var/lib/pepepow-pool/activity-snapshot.json \
  --api-base-url http://127.0.0.1:8080/api
```

Reference benchmark:

- [2026-04-13-stratum-ingress.md](/home/ubuntu/pool-pepepow/docs/benchmarks/2026-04-13-stratum-ingress.md)

---

## Security Notes

- keep daemon RPC on `127.0.0.1` or private subnet only
- do not expose daemon RPC through nginx
- do not expose `activity-snapshot.json` directly
- do not expose raw `share-events.jsonl` directly
- share-derived metrics must be treated as operational metrics, not validated
  mining proof
