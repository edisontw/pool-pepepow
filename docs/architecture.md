# PEPEPOW Pool Architecture

This document is a one-page deployer and agent reference for the current
PEPEPOW-only community pool stack.

The pool is a single-host deployment for a low-resource Ubuntu ARM64/aarch64
machine. It exposes a public website, public read-only API, and public Stratum
mining endpoint. Daemon RPC, wallet RPC, runtime files, submit controls, and
payout controls remain private/operator-only.

The current stack has active Stratum ingress, daemon-template-backed mining,
candidate follow-up, controlled submitblock validation, public manual payment
records, and private operator-owned auto wallet payout self-test tooling. It
does not claim public automatic payout readiness.

## ASCII Diagram

```text
                          public internet
                                |
                         +------v------+
                         |    nginx    |
                         +------+------+
                                |
             +------------------+------------------+
             |                                     |
      static frontend                       read-only API
  apps/frontend/site                         apps/api
             |                                     |
             |                            snapshot reads only
             |                                     |
             |        +----------------------------+----------------------------+
             |        |                            |                            |
             |  pool-snapshot.json        activity-snapshot.json       payments-snapshot.json
             |        ^                            ^                            ^
             |        |                            |                            |
             |  pool-core producer          Stratum ingress             payout tooling
             |        |                            |                            |
             |  private daemon RPC      share-events.jsonl        payout-candidates.json
             |        |                            ^
             |     PEPEPOWd                      miners
             |
      API-only browser reads
```

## Component Table

| Component | Path / service | Purpose | Boundary |
|---|---|---|---|
| `PEPEPOWd` | external daemon process | Chain state, block templates, submitblock target, wallet backend when used by operator tooling | Private daemon RPC and wallet RPC only |
| pool-core producer | `apps/pool-core/producer.py`, `pepepow-pool-core.service` | Reads daemon data and writes `pool-snapshot.json` | Private process, public data only through API |
| Stratum ingress | `apps/pool-core/stratum_ingress.py`, `pepepow-pool-stratum.service` | Miner TCP ingress, daemon-template jobs, share/activity tracking, candidate event recording | Public Stratum TCP, private runtime files |
| API | `apps/api`, `pepepow-pool-api.service` | Serves read-only JSON from snapshots and safe sidecar snapshots | Public HTTP through nginx |
| frontend | `apps/frontend/site`, `pepepow-pool-frontend.service` or nginx static root | Public static website | Public, API-only reads |
| nginx | `ops/nginx` examples | HTTPS, static frontend, API proxy | Public web boundary |
| ops scripts | `ops/scripts` | Health checks, Stratum ops, candidate follow-up, payout review, private self-test commands | Operator-only shell access |

## Data Flow

```text
miner -> Stratum ingress -> share-events.jsonl
Stratum ingress -> activity-snapshot.json
pool-core producer -> pool-snapshot.json
API -> frontend
candidate event -> submit outcome -> accepted-candidates snapshot
payout candidate -> payment snapshot
```

Details:

- Miners connect to Stratum on port `39333`.
- Stratum ingress records accepted/rejected share activity and writes
  `activity-snapshot.json`.
- The producer reads daemon RPC privately and writes `pool-snapshot.json`.
- The API reads snapshots and exposes public JSON endpoints.
- The frontend reads API endpoints only.
- Candidate follow-up creates accepted-candidate observations.
- Payout tooling creates payout candidates and payment snapshots for public
  payment views after operator review or private self-test sends.

## Public / Private Boundary

| Surface | Public? | Notes |
|---|---:|---|
| Website | Yes | Static frontend via nginx |
| API | Yes | Read-only `/api/*` JSON |
| Stratum port `39333` | Yes | Miner-facing TCP endpoint |
| daemon RPC | No | Bind to localhost/private network only |
| wallet RPC | No | Operator-only |
| raw JSONL logs | No | Runtime internals, not frontend/API public files |
| runtime snapshots | No direct public file access | API may read and summarize |
| submit controls | No | Operator-only guarded commands |
| payout controls | No | Operator-only guarded commands |
| Redis | No | Not required; if ever added, keep private |

## Runtime File Ownership

| File | Written by | Read by | Public? |
|---|---|---|---|
| `pool-snapshot.json` | pool-core producer | API | No direct public access |
| `activity-snapshot.json` | Stratum ingress | API, ops scripts | No direct public access |
| `share-events.jsonl` | Stratum ingress | ops/replay tooling only | No |
| `candidate-events.jsonl` | Stratum ingress | bounded ops tooling | No |
| `candidate-followup-events.jsonl` | follow-up tooling | ops tooling | No |
| `accepted-candidates.json` | accepted-candidate tracker | API, ops tooling | API exposes summarized data |
| `rounds-snapshot.json` | round tracker | API, payout tooling | API exposes summarized data |
| `payout-candidates.json` | payout helper | payout tooling | No direct public access |
| `payments-snapshot.json` | payout helper | API, frontend | API exposes public payment records |
| `launch.env` | live Stratum script | systemd/ops scripts | No |

## systemd Service Ownership

| Service | Owns / starts | Typical restart reason |
|---|---|---|
| `pepepow-pool-core.service` | pool-core snapshot producer | Producer, daemon RPC config, snapshot path changes |
| `pepepow-pool-stratum.service` | Stratum ingress | Mining/Stratum config or pool-core runtime changes |
| `pepepow-pool-api.service` | API service | API code/config changes |
| `pepepow-pool-frontend.service` | Static frontend service when used | Static site changes if served by service |
| nginx | Public web/API routing | TLS, static root, reverse proxy changes |
| optional timers | Round refresh or private self-test jobs | Operator-reviewed scheduled tasks |

## Frontend Read Rule

The frontend may read:

- public API endpoints only

The frontend must not read or proxy:

- daemon RPC
- wallet RPC
- raw JSONL files
- runtime snapshots by direct file path
- submit controls
- payout/admin controls

## API Read Rule

The API may read:

- `pool-snapshot.json`
- `activity-snapshot.json`
- safe sidecar snapshots such as accepted candidates, rounds, and payments

The API should not parse raw JSONL on the public request path unless that path
is already implemented safely and bounded. Prefer snapshot-first reads and
pre-aggregated sidecar files.

Current public endpoints include:

- `GET /api/health`
- `GET /api/pool/summary`
- `GET /api/network/summary`
- `GET /api/blocks`
- `GET /api/accepted-candidates`
- `GET /api/rounds`
- `GET /api/payments`
- `GET /api/miner/<wallet>`
- `GET /api/stats`
- `GET /api/status`

## Agent Modification Guide

Use these ownership boundaries for future changes:

- Frontend changes: `apps/frontend/site`
- API changes: `apps/api`
- Stratum/mining changes: `apps/pool-core`
- Ops script changes: `ops/scripts`
- systemd/nginx changes: `ops/systemd`, `ops/nginx`
- Documentation changes: `docs`

Keep changes scoped. Do not alter Stratum, daemon RPC, wallet RPC, payout,
nginx, or systemd behavior when the request is frontend/API/docs-only.
