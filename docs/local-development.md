# Local Development

## Services

This round exposes four useful local processes:

- API on `127.0.0.1:8080`
- frontend static site on `127.0.0.1:3000`
- Stratum ingress on the configured TCP port
- optional runtime snapshot producer under `apps/pool-core`

The frontend and API can run without daemon because the API falls back to the
repository mock snapshot and can still overlay live activity from
`activity-snapshot.json`.

Current Stratum job mode is synthetic/fake work only. It exists to improve
generic Stratum v1 miner compatibility, not to represent real blockchain work.
Shares accepted through this path are non-validated and not blockchain verified.

## API Startup

```bash
cd /home/ubuntu/pool-pepepow/apps/api
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Stratum Ingress Startup

```bash
cd /home/ubuntu/pool-pepepow/apps/pool-core
python3 stratum_ingress.py
```

## Producer Startup

If local daemon RPC is configured:

```bash
cd /home/ubuntu/pool-pepepow/apps/pool-core
python3 producer.py --once
```

Important:

- configure RPC in `~/.PEPEPOWcore/PEPEPOW.conf`
- stop `PEPEPOWd` and start it again after changing RPC settings

## Frontend Startup

```bash
cd /home/ubuntu/pool-pepepow/apps/frontend/site
python3 -m http.server 3000
```

## Useful Environment Overrides

API:

- `PEPEPOW_POOL_API_RUNTIME_SNAPSHOT_PATH`
- `PEPEPOW_POOL_API_FALLBACK_SNAPSHOT_PATH`
- `PEPEPOW_POOL_API_ACTIVITY_SNAPSHOT_PATH`
- `PEPEPOW_POOL_API_STALE_AFTER_SECONDS`

Pool core / Stratum:

- `PEPEPOWD_RPC_URL`
- `PEPEPOWD_RPC_USER`
- `PEPEPOWD_RPC_PASSWORD`
- `PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT`
- `PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_OUTPUT`
- `PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH`
- `PEPEPOW_POOL_CORE_STRATUM_BIND_HOST`
- `PEPEPOW_POOL_CORE_STRATUM_BIND_PORT`
- `PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY`
- `PEPEPOW_POOL_CORE_SYNTHETIC_JOB_INTERVAL_SECONDS`
- `PEPEPOW_POOL_CORE_ACTIVITY_LOG_ROTATE_BYTES`
- `PEPEPOW_POOL_CORE_ACTIVITY_LOG_RETENTION_FILES`

## Tests

```bash
cd /home/ubuntu/pool-pepepow
python3 -m unittest discover tests
```

## Quick Smoke Test

Start API and Stratum ingress, then run:

```bash
cd /home/ubuntu/pool-pepepow
python3 apps/pool-core/tools/generate_shares.py \
  --host 127.0.0.1 \
  --port 3333 \
  --rate 2 \
  --duration 5 \
  --connections 1 \
  --activity-log-path /var/lib/pepepow-pool/share-events.jsonl \
  --activity-snapshot-path /var/lib/pepepow-pool/activity-snapshot.json \
  --api-base-url http://127.0.0.1:8080/api
```

Then verify:

```bash
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/pool/summary
```

Look for:

- `activityMode = stratum-share-ingest`
- `activityDerivedFromShares = true`
- `blockchainVerified = false`
- standard Stratum v1 `mining.subscribe` response tuples plus extranonce fields
- no-op success on `mining.extranonce.subscribe` for miner compatibility
- synthetic `mining.set_difficulty` / `mining.notify` after authorize
- non-zero `activeMiners` or `activeWorkers`

## Current Data Boundary

- runtime snapshot: `/var/lib/pepepow-pool/pool-snapshot.json`
- activity snapshot: `/var/lib/pepepow-pool/activity-snapshot.json`
- share log: `/var/lib/pepepow-pool/share-events.jsonl`
- rotated share logs: `/var/lib/pepepow-pool/share-events.<first>-<last>.jsonl`
- fallback snapshot: `apps/api/data/mock/pool-snapshot.json`

API behavior:

- runtime snapshot first
- fallback snapshot second
- optional activity snapshot overlay on top

Restart recovery is snapshot-first and only replays the retained rolling tail
needed for `1m` / `5m` / `15m` activity windows.

## Benchmarks

Reference load results:

- [2026-04-13-stratum-ingress.md](/home/ubuntu/pool-pepepow/docs/benchmarks/2026-04-13-stratum-ingress.md)
