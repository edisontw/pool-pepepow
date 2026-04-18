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
- progressively validated single-coin pool stack

It is not currently intended to be:

- a large-scale commercial mining pool
- a multi-coin switching platform
- an exchange-integrated payout system
- a complex user-account platform

The immediate objective is a reliable single-coin PEPEPOW stack with:

- real miner ingress
- lightweight activity accounting
- daemon-template-backed mining progression
- controlled candidate preparation and dry-run submission
- a public API/frontend that do not directly depend on raw daemon RPC paths

---

## Architecture Principles

### 1. Single-Coin First

The system is designed specifically for PEPEPOW in the initial phase.

### 2. Low Coupling

Separate these concerns as much as possible:

- blockchain daemon access
- Stratum ingress and mining validation
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

### 6. Controlled Submission Safety

Candidate preparation and real block submission must remain distinct. Real
submission must stay explicitly gated.

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
- provide block templates for mining work
- accept controlled future block submission
- provide later wallet and payout functionality

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

### Baseline Responsibilities

- accept miner connections via Stratum
- accept `mining.subscribe`
- accept `mining.authorize`
- accept `mining.submit`
- append submitted share events to JSONL
- maintain lightweight in-memory wallet/worker accounting
- write an additive activity snapshot

### Current In-Progress Responsibilities

- retrieve daemon-backed template work
- construct and track template-backed jobs
- validate submitted shares against current work and targets
- distinguish valid pool shares from block candidates
- prepare candidate artifacts when block target is met
- support no-send / dry-run submit preparation
- keep real block submission behind explicit flags

### Later Responsibilities

- controlled real block submission
- round and block-state tracking
- payout accounting inputs
- later payout workflow integration

### Current Scope

- PEPEPOW only
- hoohash-pepew / hoohashv110-pepew only
- wallet-address-based miner identity
- no user account system
- no mandatory Redis requirement

### Current Non-Goals

- multi-coin work routing
- exchange payouts
- complex user auth
- heavy runtime coordination infrastructure without clear need

### Design Notes

Pool core is intentionally split into low-coupling paths:

- daemon-aware runtime snapshot producer
- Stratum ingress and activity snapshot writer
- daemon-template-backed validation / candidate-prep path
- later controlled submit path

This split is intended to preserve baseline share-ingest observability even when
daemon-backed mining paths are degraded or unavailable.

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
- candidate / validation metadata should be surfaced only through controlled,
  summarized, frontend-safe fields when exposed at all

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

### UI Interpretation Policy

The frontend should distinguish where practical between:

- chain-derived information
- share-derived activity information
- current pool operational state
- later validated mining or candidate-related states

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
- controlled feature flag deployment for mining milestones

### Operational Principles

- every major service should be restartable independently
- configuration should be explicit and documented
- rollback should be possible
- deployments should be reproducible on a fresh host
- higher-risk mining features should be separately gateable

---

## Suggested Initial Runtime Components

A practical current stack consists of:

- `PEPEPOWd`
- pool-core snapshot producer
- Stratum ingress
- activity snapshot writer
- template-backed job / validation path inside pool core
- stats/API service
- frontend service
- `nginx`
- `systemd`

Optional later components:

- controlled submission worker or isolated submission path
- payout worker
- notification worker
- Redis only if clearly justified

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
- baseline share ingest
- in-memory activity accounting
- writes `share-events.jsonl`
- writes `activity-snapshot.json`

### Service D: Validation / Candidate Path

This may remain inside pool core initially, but conceptually it is a separate
responsibility:

- template-backed job handling
- share validation
- pool share vs block candidate split
- candidate artifact preparation
- no-send dry-run output
- controlled submit hook

### Service E: Stats/API

- public or reverse-proxied API
- read-oriented
- cache-first
- merges runtime/fallback snapshot with activity snapshot
- later may expose summarized mining-validation status

### Service F: Frontend

- public web interface
- static or semi-dynamic UI

### Service G: Reverse Proxy

- nginx
- TLS
- routing
- rate limiting

---

## Data Flow

### Baseline Share Flow

1. miner connects to Stratum endpoint
2. miner sends `mining.subscribe`
3. miner sends `mining.authorize`
4. miner sends `mining.submit`
5. Stratum ingress records the share event
6. share is appended to `share-events.jsonl`
7. in-memory wallet/worker accounting is updated
8. `activity-snapshot.json` is written atomically
9. API loads runtime or fallback base snapshot
10. API overlays activity fields from `activity-snapshot.json`
11. frontend displays merged pool/network/miner state

### Current Template-Backed Validation Flow

1. pool retrieves daemon-backed template work
2. pool constructs or refreshes template-backed job state
3. miner connects and receives work context
4. miner submits share
5. pool reconstructs the relevant candidate header / job context
6. pool validates the submitted share against applicable target logic
7. pool classifies:
   - invalid share
   - valid pool share
   - block candidate
8. if block candidate conditions are met, pool prepares candidate artifact
9. if dry-run mode is enabled, submission payload is prepared but not sent
10. if real submission is disabled, processing stops at recorded candidate state

### Controlled Submission Flow

1. candidate artifact exists
2. explicit submit-enable flag is on
3. pool submits the candidate to daemon
4. daemon accepts or rejects
5. pool records submission result for audit and follow-up
6. later block-state tracking consumes this result path

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

Current in-progress mining additions may include:

- valid pool share indicators
- candidate-prep counters
- dry-run / submit readiness state

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
- later validated pool block states
- later candidate and submission results where summarized appropriately

### Miner Domain

- wallet
- estimated hashrate
- workers
- per-wallet share count
- per-worker share count
- rolling windows
- last share timestamps
- later balance / payment data

---

## Trust Model

### Current Trust Boundaries

- chain fields remain owned by the runtime / fallback chain snapshot path
- share-derived metrics are not automatically equivalent to chain-verified
  mining success
- estimated hashrate may still depend on pool-side assumptions
- valid pool shares do not automatically imply block candidates
- candidate-prepared state does not automatically imply submitted or accepted
  block state

### Operational Interpretation

The architecture must keep these distinctions explicit:

- share-ingest success
- share-validation success
- candidate-preparation success
- real submission success
- confirmed block state

---

## Security Boundaries

### Must Remain Internal

- daemon RPC
- real submission control flags and tooling
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
- keep block submission off by default

---

## Performance Strategy

Given the small server size, the architecture enforces:

- cached summary endpoints
- bounded polling intervals
- no heavy frontend auto-refresh loops
- no expensive repeated wallet scans from public pages
- in-memory rolling windows for live activity
- snapshot reads instead of raw log parsing on request paths
- bounded daemon-template refresh behavior
- controlled candidate-prep and submit logic

---

## Extensibility Strategy

The architecture should later support:

- richer validated share handling
- `mining.notify` and difficulty management improvements
- round and block-state tracking
- payout accounting
- better health reporting
- notifications
- optional Redis-backed coordination
- future horizontal separation of services

These remain secondary to current correctness and stability.

---

## Current Repository Implementation

The current repository should be understood as having progressed beyond a pure
share-ingest-only baseline.

### Implemented / Baseline

- lightweight public API service under `apps/api`
- static public frontend under `apps/frontend/site`
- daemon-aware runtime snapshot producer under `apps/pool-core/producer.py`
- Stratum ingress under `apps/pool-core/stratum_ingress.py`
- additive activity snapshot overlay in `apps/api/store.py`
- share-derived accounting contracts under `apps/pool-core/contracts`
- systemd and nginx deployment skeleton under `ops/`

### Current In Progress

- daemon-template-backed mining flow
- share validation progression
- pool share vs block candidate separation
- candidate preparation
- dry-run submission preparation
- controlled real submission gating

### Not Yet Implemented as Full Pool

- mature round/block lifecycle tracking
- payout processing
- long-term accounting layer
- Redis-backed coordination as a required dependency

---

## Success Criteria

### Baseline Success

The current baseline architecture is successful when:

- miners can connect successfully
- submitted shares are accepted into the ingest pipeline
- wallet and worker activity is tracked
- activity snapshots are written atomically
- API exposes live miner activity without raw daemon dependency
- services restart and recover cleanly
- the stack can be reproduced on a fresh server

### Current Mining-Milestone Success

The current mining milestone is successful when:

- block templates are retrieved correctly
- share validation behaves correctly
- valid pool shares are distinguishable from block candidates
- candidate preparation is correct
- dry-run data is correct
- real submission remains controlled and off by default
- submission results are logged when enabled

### Later Full-Pool Success

The full architecture will be successful when:

- block states are tracked correctly
- payout correctness is demonstrable
- pool/network/miner summaries remain accurate under validated mining
- the system is stable enough for broader controlled public use

---

## Explicit Non-Goals for Initial / Current Versions

The architecture does not attempt to solve yet:

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
5. correctness
6. extensibility
7. visual polish