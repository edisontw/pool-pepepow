# PEPEPOW Community Pool Architecture

## Overview

This document defines the target architecture for a lightweight PEPEPOW community mining pool designed for:

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

This project is intended to prioritize:

1. stability
2. simplicity
3. maintainability
4. low resource consumption
5. clean visual presentation

---

## Product Positioning

The pool is initially positioned as a:

- community pool
- learning platform
- testing-capable public mining endpoint

It is **not** initially intended to be:

- a large-scale commercial mining pool
- a multi-coin switching platform
- a profit-switching pool
- an exchange-integrated payout system
- a complex user-account platform

The first objective is to build a **reliable single-coin PEPEPOW pool** that can be operated safely on a small ARM server and improved incrementally.

---

## Architecture Principles

### 1. Single-Coin First
The system should be designed specifically for PEPEPOW in the initial phase.

- single coin
- single algorithm family
- single deployment target
- single operational context

Avoid early abstraction for multi-coin support.

### 2. Low Coupling
Separate the following concerns as much as possible:

- blockchain daemon access
- pool core logic
- stats aggregation
- frontend rendering
- ops / deployment / monitoring

### 3. Cache Before Query
The frontend should not directly depend on daemon RPC.

- pool/network stats should be aggregated
- repeated dashboard requests should hit cache or precomputed summaries
- expensive blockchain or wallet calls should be minimized

### 4. Small-Step Iteration
The architecture should allow AI agents to modify one area at a time without destabilizing the whole system.

### 5. Low-Resource Operation
Every component must be chosen with 1 core / 6 GB RAM in mind.

---

## High-Level System Layout

The system should be separated into the following logical layers:

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
- provide block templates
- accept submitted blocks
- provide wallet and payout-related functionality
- expose network state data to internal services

### Requirements
- daemon RPC must remain internal
- wallet access must not be directly exposed publicly
- configuration must be minimal and locked down
- this layer must be isolated from public website traffic

### Notes
The daemon is one of the most sensitive and resource-critical services in the system.  
No UI or external API should directly depend on raw daemon calls.

---

## 2. Pool Core Layer

### Purpose
Implements mining pool behavior.

### Main Responsibilities
- accept miner connections via stratum
- validate shares
- manage worker accounting
- build and submit candidate blocks
- manage pool rounds
- track block states
- maintain payout accounting inputs

### Initial Scope
- PEPEPOW only
- hoohash-pepew / hoohashv110-pepew only
- one payout scheme only, preferably PPLNS
- wallet-address-based miner identity
- no user account system

### Initial Non-Goals
- multi-coin switching
- exchange payouts
- complex user auth
- advanced referral systems
- per-user web dashboards requiring login

### Design Notes
The pool core should be treated as the operational engine.  
It should expose clean internal stats or data outputs that can be consumed by a separate stats/API layer.

---

## 3. Stats / API Layer

### Purpose
Acts as the translation layer between the pool backend and the frontend.

### Main Responsibilities
- aggregate pool statistics
- aggregate network statistics
- expose miner lookup endpoints
- expose blocks, payments, and workers endpoints
- provide frontend-friendly JSON responses
- reduce direct coupling between UI and backend internals

### API Goals
- stable JSON format
- cacheable responses
- low-latency reads
- safe separation from daemon internals
- reduced RPC load

### Recommended Data Groups
- pool summary
- network summary
- blocks list
- payments list
- miner summary by wallet
- worker summary by wallet
- status / health information

### Design Rules
- no public raw RPC passthrough
- expensive queries should be pre-aggregated
- API should prefer summary snapshots over real-time heavy recalculation
- allow future addition of alerting or status endpoints

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
- status and service visibility

### Frontend Priorities
- professional appearance
- modern layout
- clean data hierarchy
- responsive design
- easy wallet lookup
- copyable mining commands
- clear presentation of algorithm and connection parameters

### UI Principles
- dark professional blockchain/mining aesthetic
- PEPEPOW-oriented identity
- avoid clutter
- prioritize clarity over novelty
- support both desktop and mobile users

### Frontend Data Policy
The frontend must read from the stats/API layer, not directly from the daemon or pool internals.

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
- optional basic alerting

### Operational Principles
- every major service should be restartable independently
- configuration should be explicit and documented
- rollback should be possible
- deployments should be reproducible on a fresh host

---

## Suggested Initial Runtime Components

A practical initial stack may consist of:

- `PEPEPOWd`
- `Redis`
- pool core service
- stats/API service
- frontend service
- `nginx`
- `systemd`
- logrotate

This should remain a **single-host deployment** initially.

---

## Recommended Service Boundaries

### Service A: Daemon
- PEPEPOWd
- private RPC only

### Service B: Data Cache
- Redis
- private only

### Service C: Pool Core
- stratum
- share processing
- round and block handling

### Service D: Stats/API
- public or reverse-proxied API
- read-oriented
- lightweight
- cache-first

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

### Miner Data Flow
1. miner connects to stratum endpoint
2. pool core validates connection and difficulty policy
3. miner submits shares
4. pool core validates and records shares
5. valid candidate block is found
6. pool core submits block to daemon
7. daemon accepts or rejects block
8. pool core updates block state
9. stats/API layer exposes updated summaries
10. frontend displays updated state

### User Data Flow
1. user visits site
2. frontend requests summarized data from API
3. API returns cached or aggregated pool/network/miner data
4. user views dashboard / blocks / payments / miner status

---

## Initial Data Domains

The architecture should account for the following data domains:

### Pool Domain
- pool hashrate
- active miners
- active workers
- fee
- payout threshold
- pool luck / effort
- recent shares summary

### Network Domain
- current height
- difficulty
- network hashrate
- latest block timing
- daemon / chain status

### Block Domain
- pending
- immature
- confirmed
- orphan
- rejected or invalid if applicable

### Miner Domain
- wallet
- current estimated hashrate
- workers
- balance / pending
- total paid
- payment history
- last share timestamps

---

## Security Boundaries

### Must Remain Internal
- daemon RPC
- Redis
- wallet management endpoints
- any administrative tooling not explicitly hardened

### Publicly Exposed
- pool website
- public stats API
- stratum ports
- status/maintenance pages if needed

### Security Principles
- minimize public surface area
- avoid exposing raw internals
- isolate wallet-sensitive operations
- prefer explicit access paths

---

## Performance Strategy

Given the small server size, the architecture should enforce:

- cached summary endpoints
- bounded polling intervals
- no heavy frontend auto-refresh loops
- no expensive repeated wallet scans from public pages
- limited historical aggregation on-demand
- coarse-grained charts rather than high-frequency metrics

---

## Extensibility Strategy

The architecture should support later addition of:

- improved charts
- Telegram/Discord notifications
- richer miner analytics
- admin pages
- better health reporting
- external status pages
- future horizontal separation of services

However, these must remain **secondary to core correctness and stability**.

---

## Explicit Non-Goals for Initial Version

The initial architecture should **not** attempt to solve:

- multi-region pool deployment
- distributed stratum clusters
- complex HA topologies
- large-scale SQL analytics
- advanced account/auth systems
- automated exchange-based payouts
- generalized multi-coin orchestration

---

## MVP Architecture Success Criteria

The architecture is considered successful for MVP when:

- miners can connect successfully
- shares are accepted and tracked
- block templates are retrieved correctly
- valid blocks can be submitted
- pool/network/miner summaries can be displayed
- services can restart and recover cleanly
- the stack can be reproduced on a fresh server

---

## Decision Priority Order

When tradeoffs occur, prioritize in this order:

1. stability
2. simplicity
3. maintainability
4. observability
5. extensibility
6. visual polish