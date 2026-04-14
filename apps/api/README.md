# API Service

This directory contains the lightweight PEPEPOW public API service.

## Scope

- serves public, frontend-safe JSON only
- reads snapshot JSON produced by `apps/pool-core`
- overlays optional share-derived activity snapshot data
- prefers runtime snapshot and falls back to repository mock data
- never calls daemon RPC directly
- exposes runtime/fallback and activity metadata without changing core response shapes

## Endpoints

- `GET /api/health`
- `GET /api/pool/summary`
- `GET /api/network/summary`
- `GET /api/blocks`
- `GET /api/payments`
- `GET /api/miner/<wallet>`

## Local Run

```bash
cd /home/ubuntu/pool-pepepow/apps/api
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Configuration

- `PEPEPOW_POOL_API_HOST`
- `PEPEPOW_POOL_API_PORT`
- `PEPEPOW_POOL_API_VERSION`
- `PEPEPOW_POOL_API_RUNTIME_SNAPSHOT_PATH`
- `PEPEPOW_POOL_API_FALLBACK_SNAPSHOT_PATH`
- `PEPEPOW_POOL_API_ACTIVITY_SNAPSHOT_PATH`
- `PEPEPOW_POOL_API_CACHE_TTL_SECONDS`
- `PEPEPOW_POOL_API_STALE_AFTER_SECONDS`
- `PEPEPOW_POOL_API_ALLOWED_WALLET_PATTERN`

`PEPEPOW_POOL_API_SNAPSHOT_PATH` is still accepted as a legacy alias for the
runtime snapshot path.

## Snapshot Source Priority

1. runtime snapshot, normally `/var/lib/pepepow-pool/pool-snapshot.json`
2. fallback snapshot, normally `apps/api/data/mock/pool-snapshot.json`
3. additive activity snapshot overlay, normally `/var/lib/pepepow-pool/activity-snapshot.json`
4. `503` only when both are unavailable

`/api/health` reports:

- `snapshotSource`
- `snapshotAgeSeconds`
- `degraded`
- `stale`
- `lastError`
- `chainState`
- `activityMode`
- `activityDataStatus`

The public API shape remains stable for the frontend. New status metadata is
additive only.
