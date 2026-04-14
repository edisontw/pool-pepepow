# PEPEPOW Community Pool Architecture

## Overview

This document defines the target architecture for a lightweight PEPEPOW
community mining pool designed for:

- PEPEPOW only
- Oracle Cloud small instance deployment
- ARM64 / aarch64 compatibility
- simple maintenance
- AI-agent-friendly development and iteration
- clean, professional frontend presentation

The initial target environment is:

- 1 vCPU
- 6 GB RAM
- Ubuntu
- systemd
- single-host deployment

This project prioritizes:

1. stability
2. simplicity
3. maintainability
4. low resource consumption
5. clean public presentation

---

## Product Positioning

The pool is currently positioned as a:

- community pool
- learning platform
- testing-capable public mining endpoint

It is not currently intended to be:

- a large-scale commercial mining pool
- a multi-coin switching platform
- an exchange-integrated payout system
- a complex user-account platform

The immediate objective is a reliable single-coin PEPEPOW stack with real miner
ingress, lightweight activity accounting, and a public API/frontend that do not
depend on a healthy daemon for share ingest.

---

## Architecture Principles

### 1. Single-Coin First

The system is designed specifically for PEPEPOW in the initial phase.

### 2. Low Coupling

Separate these concerns as much as possible:

- blockchain daemon access
- Stratum ingress and share ingest
- activity accounting
- stats aggregation
- frontend rendering
- ops / deployment / monitoring

### 3. Cache Before Query

The frontend should not directly depend on daemon RPC.

### 4. Small-Step Iteration

The architecture should allow one subsystem at a time to change without
destabilizing the rest of the stack.

### 5. Low-Resource Operation

Every component must fit a 1 core / 6 GB RAM host.

---

## High-Level System Layout

The system is separated into these logical layers:

1. Blockchain / Daemon Layer
2. Pool Core Layer
3. Stats / API Layer
4. Frontend / Portal Layer
5. Ops / Runtime Layer

---

## 1. Blockchain / Daemon Layer

### Purpose

Provides direct interaction with the PEPEPOW blockchain.

### Main Responsibilities

- run `PEPEPOWd`
- expose local RPC
- provide chain state for runtime snapshots
- provide future block templates
- provide future block submission path
- provide future wallet and payout functionality

### Requirements

- daemon RPC must remain internal
- wallet access must not be directly exposed publicly
- configuration must be minimal and locked down
- this layer must be isolated from public website traffic

### Notes

The daemon is sensitive and resource-critical. No UI or public API path should
directly depend on raw daemon calls.

---

## 2. Pool Core Layer

### Purpose

Implements pool-side mining behavior.

### Current Responsibilities

- accept miner connections via Stratum
- accept `mining.subscribe`
- accept `mining.authorize`
- accept `mining.submit`
- append submitted shares to JSONL
- maintain lightweight in-memory wallet/worker accounting
- write an additive activity snapshot

### Future Responsibilities

- validate shares
- manage difficulty and work distribution
- build and submit candidate blocks
- manage rounds and block states
- provide payout accounting inputs

### Current Scope

- PEPEPOW only
- hoohash-pepew / hoohashv110-pepew only
- wallet-address-based miner identity
- no user account system
- no Redis requirement

### Current Non-Goals

- share validation against daemon work
- payout processing
- exchange payouts
- complex user auth
- Redis-backed runtime coordination

### Design Notes

Pool core is currently split into two low-coupling paths:

- daemon-aware runtime snapshot producer
- daemon-independent Stratum ingress and activity snapshot writer

---

## 3. Stats / API Layer

### Purpose

Acts as the translation layer between the pool backend and the frontend.

### Main Responsibilities

- aggregate pool statistics
- aggregate network statistics
- expose miner lookup endpoints
- expose blocks and payments endpoints
- merge activity snapshot data over runtime or fallback chain snapshots
- provide frontend-friendly JSON responses

### API Goals

- stable JSON format
- cacheable responses
- low-latency reads
- safe separation from daemon internals
- reduced RPC load

### Current Public Endpoints

- `GET /api/health`
- `GET /api/pool/summary`
- `GET /api/network/summary`
- `GET /api/blocks`
- `GET /api/payments`
- `GET /api/miner/<wallet>`

### Design Rules

- no public raw RPC passthrough
- expensive queries should be pre-aggregated
- API should prefer summary snapshots over real-time recalculation
- activity overlay must be additive and must not change endpoint shapes

---

## 4. Frontend / Portal Layer

### Purpose

Provides the public-facing mining pool interface.

### Main Responsibilities

- landing page
- live pool summary
- miner lookup
- blocks view
- payments view
- connection instructions
- notices and maintenance information
- service visibility

### Frontend Data Policy

The frontend must read from the stats/API layer, not directly from the daemon
or raw pool internals.

---

## 5. Ops / Runtime Layer

### Purpose

Supports deployment, reliability, recoverability, and maintenance.

### Main Responsibilities

- service lifecycle management with systemd
- reverse proxy with nginx
- TLS termination
- log management
- backup and restore procedures
- process isolation
- health checks

### Operational Principles

- every major service should be restartable independently
- configuration should be explicit and documented
- rollback should be possible
- deployments should be reproducible on a fresh host

---

## Suggested Initial Runtime Components

A practical current stack consists of:

- `PEPEPOWd`
- pool-core snapshot producer
- Stratum ingress
- activity snapshot writer
- stats/API service
- frontend service
- `nginx`
- `systemd`

Optional future components:

- `Redis`
- payout worker
- notification worker

This should remain a single-host deployment initially.

---

## Recommended Service Boundaries

### Service A: Daemon

- `PEPEPOWd`
- private RPC only

### Service B: Runtime Snapshot Producer

- daemon-aware chain snapshot generation
- reads low-cost RPC only
- writes `pool-snapshot.json`

### Service C: Stratum Ingress / Activity Path

- Stratum listener
- share ingest
- in-memory activity accounting
- writes `share-events.jsonl`
- writes `activity-snapshot.json`

### Service D: Stats/API

- public or reverse-proxied API
- read-oriented
- cache-first
- merges runtime/fallback snapshot with activity snapshot

### Service E: Frontend

- public web interface
- static or semi-dynamic UI

### Service F: Reverse Proxy

- nginx
- TLS
- routing
- rate limiting

---

## Data Flow

### Current Implemented Share Flow

1. miner connects to Stratum endpoint
2. miner sends `mining.subscribe`
3. miner sends `mining.authorize`
4. miner sends `mining.submit`
5. Stratum ingress accepts the share without validation
6. share is appended to `share-events.jsonl`
7. in-memory wallet/worker accounting is updated
8. `activity-snapshot.json` is written atomically
9. API loads runtime or fallback base snapshot
10. API overlays activity fields from `activity-snapshot.json`
11. frontend displays merged pool/network/miner state

### Future Validated Pool Flow

1. miner connects to Stratum endpoint
2. pool assigns work and difficulty
3. miner submits share
4. pool validates share against daemon-backed work
5. valid candidate block is found
6. pool submits block to daemon
7. daemon accepts or rejects block
8. pool updates round and block state
9. stats/API layer exposes validated summaries

### User Data Flow

1. user visits site
2. frontend requests summarized data from API
3. API returns cached or aggregated pool/network/miner data
4. user views dashboard / blocks / payments / miner status

---

## Initial Data Domains

### Pool Domain

- pool hashrate
- active miners
- active workers
- fee
- payout threshold metadata
- worker distribution
- recent share summaries
- rolling windows for `1m`, `5m`, `15m`

### Network Domain

- current height
- difficulty
- network hashrate
- latest block timing
- daemon / chain status

### Block Domain

- observed network blocks
- block height
- block hash
- found time
- confirmations
- future validated pool block states

### Miner Domain

- wallet
- estimated hashrate
- workers
- per-wallet share count
- per-worker share count
- rolling windows
- last share timestamps
- future balance / payment data

---

## Current Trust Model

- pool activity metrics are derived from shares
- share-derived metrics are not blockchain verified
- estimated hashrate uses an assumed share difficulty
- accepted shares at this stage do not imply valid shares
- chain fields remain owned by the runtime/fallback chain snapshot path

---

## Security Boundaries

### Must Remain Internal

- daemon RPC
- future Redis deployments
- wallet management endpoints
- administrative tooling not explicitly hardened

### Publicly Exposed

- pool website
- public stats API
- Stratum port
- status / maintenance pages if needed

### Security Principles

- minimize public surface area
- avoid exposing raw internals
- isolate wallet-sensitive operations
- prefer explicit access paths

---

## Performance Strategy

Given the small server size, the architecture enforces:

- cached summary endpoints
- bounded polling intervals
- no heavy frontend auto-refresh loops
- no expensive repeated wallet scans from public pages
- in-memory rolling windows for live activity
- snapshot reads instead of raw log parsing on request paths

---

## Extensibility Strategy

The architecture should later support:

- validated share handling
- `mining.notify` and difficulty management
- block submission
- richer miner analytics
- better health reporting
- notifications
- optional Redis-backed coordination
- future horizontal separation of services

These remain secondary to current correctness and stability.

---

## Current Repository Implementation

The current repository intentionally stops below full pool functionality.

### Implemented Now

- lightweight public API service under `apps/api`
- static public frontend under `apps/frontend/site`
- daemon-aware runtime snapshot producer under `apps/pool-core/producer.py`
- daemon-independent Stratum ingress under `apps/pool-core/stratum_ingress.py`
- additive activity snapshot overlay in `apps/api/store.py`
- share-derived accounting contracts under `apps/pool-core/contracts`
- systemd and nginx deployment skeleton under `ops/`

### Not Yet Implemented

- block template retrieval for mining
- real share validation
- candidate block detection and submission
- payout processing
- Redis-backed runtime coordination

---

## Success Criteria

### Current Round Success

The current architecture is successful when:

- miners can connect successfully
- submitted shares are accepted into the ingest pipeline
- wallet and worker activity is tracked
- activity snapshots are written atomically
- API exposes live miner activity without daemon dependence
- services restart and recover cleanly
- the stack can be reproduced on a fresh server

### Future Full-Pool Success

The full architecture will be successful when:

- validated shares are tracked correctly
- block templates are retrieved correctly
- valid blocks can be submitted
- payout correctness is demonstrable
- pool/network/miner summaries remain accurate under validated mining

---

## Explicit Non-Goals for Initial Version

The initial architecture does not attempt to solve:

- multi-region pool deployment
- distributed Stratum clusters
- complex HA topologies
- large-scale SQL analytics
- advanced account/auth systems
- automated exchange-based payouts
- generalized multi-coin orchestration

---

## Decision Priority Order

When tradeoffs occur, prioritize in this order:

1. stability
2. simplicity
3. maintainability
4. observability
5. extensibility
6. visual polish
