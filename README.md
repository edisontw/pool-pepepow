# pool-pepepow

PEPEPOW community pool skeleton for a single low-resource ARM64 Ubuntu host.

## Current Scope

This repository currently contains:

- a lightweight public API service
- a static frontend that reads the API only
- a minimal `pool-core` runtime snapshot producer
- a daemon-independent Stratum ingress service with synthetic Stratum v1 job broadcast
- a local JSONL share ingest and accounting pipeline
- bounded JSONL rotation/retention plus snapshot-first replay
- systemd/nginx/env deployment examples
- fallback mock snapshot data

This round still does not implement:

- real share validation against daemon templates
- real block template retrieval
- candidate block handling or `submitblock`
- payout automation
- Redis-backed runtime accounting

## Services

- `apps/api`
  - Flask + Waitress
  - reads runtime snapshot first, fallback snapshot second
- `apps/frontend/site`
  - static HTML/CSS/JS
  - consumes public API only
- `apps/pool-core`
  - read-only daemon adapter
  - daemon-independent Stratum ingress
  - synthetic/fake `mining.set_difficulty` and `mining.notify`
  - writes public runtime snapshot JSON
  - writes additive activity snapshot JSON
  - merges local share/activity accounting into the snapshot

## Public And Private Boundaries

Public:

- nginx website
- nginx API
- future stratum endpoint

Private only:

- PEPEPOWd RPC
- Redis
- payout tooling
- admin automation

## Local Start

API:

```bash
cd /home/ubuntu/pool-pepepow/apps/api
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Producer once:

```bash
cd /home/ubuntu/pool-pepepow/apps/pool-core
python3 producer.py --once
```

Frontend:

```bash
cd /home/ubuntu/pool-pepepow/apps/frontend/site
python3 -m http.server 3000
```

## Runtime Snapshot Flow

1. `PEPEPOWd` exposes read-only RPC on localhost/private network only
2. `apps/pool-core/producer.py` reads low-cost RPC data and writes a snapshot
3. `apps/pool-core` optionally reads a local JSONL share log for miner activity
4. `apps/api` serves the runtime snapshot
5. if runtime snapshot is missing, API falls back to repository mock data
6. frontend reads only `GET /api/*`

Current Stratum job flow is synthetic/fake work for protocol compatibility only.
It is non-validated, not blockchain verified, and does not use real templates yet.

## RPC Enablement

Daemon RPC must be explicitly configured in `~/.PEPEPOWcore/PEPEPOW.conf`.
After editing the file, stop `PEPEPOWd` and start it again. Do not rely on
reload behavior.

The current live host uses `rpcport=8834`; keep repo env files aligned with the
working daemon configuration.

`8834` is the daemon RPC port and should stay bound to `127.0.0.1` only.
`8833` is the P2P network port and is not used by the pool API or producer.

## Reindex-Safe Validation

While the daemon is running with `-reindex` or is otherwise unsynced, this round
accepts validation of:

- RPC connectivity and authentication
- `producer.py --once`
- runtime snapshot generation
- API runtime-vs-fallback behavior
- stale/degraded metadata
- local share/activity accounting

This round does not treat reindex-time height, difficulty, or latest block data
as final live acceptance.

## Verification

```bash
cd /home/ubuntu/pool-pepepow
python3 -m unittest discover tests
```

See:

- [docs/local-development.md](/home/ubuntu/pool-pepepow/docs/local-development.md)
- [docs/oracle-ubuntu-deployment.md](/home/ubuntu/pool-pepepow/docs/oracle-ubuntu-deployment.md)
- [docs/runbooks/snapshot-pipeline.md](/home/ubuntu/pool-pepepow/docs/runbooks/snapshot-pipeline.md)
