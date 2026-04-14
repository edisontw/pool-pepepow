# PEPEPOW Community Pool Requirements

## Purpose

This document defines the current and future requirements for the PEPEPOW
community mining pool project.

The repository currently implements a daemon-independent share-ingest-first
path. It does not yet implement full mining validation, block submission, or
payout handling. This document separates what is required now from what remains
future full-pool work.

---

## 1. Project Scope

### In Scope Now

- PEPEPOW-only pool software
- hoohash-pepew / hoohashv110-pepew presentation and connection metadata
- public-facing mining website
- minimal Stratum ingress
- share accounting by wallet and worker
- daemon-independent activity snapshots
- public API backed by runtime/fallback snapshot plus activity overlay
- deployable on Oracle Cloud ARM64 small instance

### Future Full-Pool Scope

- share validation against daemon work
- block template retrieval
- candidate block detection
- block submission
- round tracking
- payout accounting and payments

### Out of Scope for Initial Version

- multi-coin support
- exchange-based payouts
- user registration and login
- large admin panel
- heavy analytical backend
- complex referral systems
- large-scale multi-server production orchestration

---

## 2. Functional Requirements

## 2.1 Current Implemented / Current Required

### FR-001: Miner Connectivity

The pool must provide at least one public Stratum endpoint that miners can
connect to.

### FR-002: Share Ingest

The current system must accept submitted shares into the ingest pipeline even
when daemon RPC is unavailable.

### FR-003: Share Accounting

The system must track shares by wallet and worker.

### FR-004: Miner Identity Model

Miner identity must be wallet-address-based in the current version.

### FR-005: Worker Visibility

The system must distinguish workers under the same wallet when possible.

### FR-006: Activity Snapshot

The system must write an internal activity snapshot derived from shares. This
snapshot must be additive and must not replace chain data ownership.

### FR-007: Pool Summary API

The system must provide an API endpoint for summary pool statistics.

### FR-008: Network Summary API

The system must provide an API endpoint for basic network statistics.

### FR-009: Miner Lookup API

The system must provide an API endpoint for wallet-based miner lookup.

### FR-010: Blocks API

The system must provide an API endpoint for recent blocks and their observed
states from the chain snapshot path.

### FR-011: Payments API

The system must provide an API endpoint for recent payments, even if the
current implementation is placeholder-only.

### FR-012: Worker Summary API

The system should provide worker-level summary data where available.

### FR-013: Cache-Friendly API

The public API should return pre-aggregated or cacheable data rather than
triggering heavy live recalculation.

### FR-014: Activity Overlay

The API must support additive share-derived activity overlay without breaking
existing endpoint shapes.

### FR-015: Public Website

The project must provide a public website.

### FR-016: Landing Page

The site must have a landing page describing the pool and connection
information.

### FR-017: Mining Connection Instructions

The site must provide clear connection instructions including:

- algorithm
- Stratum endpoint
- example command lines
- wallet usage conventions
- worker naming conventions if supported

### FR-018: Pool Dashboard

The site must provide a dashboard for pool-level summary data.

### FR-019: Blocks Page

The site must provide a page listing recent blocks and statuses.

### FR-020: Payments Page

The site must provide a page listing recent payments.

### FR-021: Miner Lookup Page

The site must provide a wallet lookup page.

### FR-022: Status or Notice Visibility

The site should provide a way to display maintenance notices, upgrade notices,
or service status.

### FR-023: Copy-Friendly Commands

Mining commands and pool addresses should be easy to copy.

### FR-024: systemd Service Management

Major components must be operable as systemd services or equivalent persistent
services.

### FR-025: Reverse Proxy

The site and API should be served behind nginx or an equivalent reverse proxy.

### FR-026: TLS

Public web access should support HTTPS.

### FR-027: Logging

Major components must produce logs sufficient for troubleshooting.

### FR-028: Restart Recovery

The system must recover from service restarts without manual reconstruction of
the current share-derived activity state.

### FR-029: Deployment Documentation

The project must include documentation sufficient to reproduce deployment on a
fresh server.

### FR-030: Configuration Documentation

Key configuration files and environment variables must be documented.

---

## 2.2 Future Full-Pool Requirements

### FR-031: Share Validation

A future full-pool version must validate submitted shares and reject invalid
ones.

### FR-032: Block Template Retrieval

A future full-pool version must retrieve valid block templates from the PEPEPOW
daemon.

### FR-033: Candidate Block Handling

A future full-pool version must be able to process valid shares that form a
candidate block.

### FR-034: Block Submission

A future full-pool version must submit valid candidate blocks to the PEPEPOW
daemon.

### FR-035: Block State Tracking

A future full-pool version must track block lifecycle states, including at
minimum:

- pending
- immature
- confirmed
- orphan

### FR-036: Round Tracking

A future full-pool version must track mining rounds associated with found
blocks.

### FR-037: Payout Scheme

A future full-pool version must support one payout model only, preferably
PPLNS.

### FR-038: Balance Tracking

A future full-pool version must track pending and payable balances by wallet.

### FR-039: Minimum Payout Threshold

A future full-pool version must support a minimum payout threshold.

### FR-040: Payment History

A future full-pool version must track and display payment history by wallet.

### FR-041: Manual or Semi-Automated Payout Support

A future full-pool version may use manual or semi-automated payout flow, but
payment actions must be traceable.

### FR-042: Payout Safety

A future full-pool version must not treat immature or orphaned blocks as
eligible for payout.

---

## 3. Non-Functional Requirements

## 3.1 Performance Requirements

### NFR-001: Low Resource Usage

The system must be designed to operate on:

- 1 vCPU
- 6 GB RAM
- ARM64 / aarch64

### NFR-002: Controlled RPC Load

The architecture must minimize repeated expensive daemon RPC calls.

### NFR-003: Cache-Oriented Dashboarding

Frontend dashboards must rely on summarized or cached data whenever possible.

### NFR-004: Bounded Refresh

The frontend should avoid aggressive high-frequency auto-refresh behavior.

### NFR-005: Lightweight Stack

The initial implementation should prefer lightweight components over heavy
infrastructure.

### NFR-006: No Daemon Dependency for Share Ingress

The current share-ingest path must remain available even when daemon RPC is
unsynced, slow, or unavailable.

### NFR-007: Bounded In-Memory Accounting

The current accounting path must use lightweight in-memory state with bounded
rolling windows rather than requiring a database or Redis.

### NFR-008: Atomic Snapshot Writes

Snapshot outputs must be written atomically so the API does not serve partial
files.

### NFR-009: Stable API Under Ingest Burst

Share ingest bursts must not cause API instability or make the API parse the
raw JSONL share log on request paths.

---

## 3.2 Maintainability Requirements

### NFR-010: AI-Agent-Friendly Structure

The codebase must be organized so that AI agents can modify subsystems with
limited blast radius.

### NFR-011: Small-Step Changeability

The system should support incremental feature development and safe refactoring.

### NFR-012: Clear File and Service Boundaries

Service ownership and code boundaries must be understandable.

### NFR-013: Config Clarity

Configurations should be explicit, readable, and commented when practical.

### NFR-014: Reproducibility

A new environment should be able to reproduce the deployment from documentation
and repository contents.

---

## 3.3 Compatibility Requirements

### NFR-015: ARM64 Compatibility

All chosen components and dependencies must be reviewed for ARM64 / aarch64
compatibility.

### NFR-016: Ubuntu / systemd Compatibility

The deployment target should assume Ubuntu with systemd.

### NFR-017: PEPEPOW Compatibility

The system must remain compatible with the current PEPEPOW daemon, chain state,
and supported miner connection expectations for future validated mining work.

---

## 3.4 Usability Requirements

### NFR-018: Clear Information Hierarchy

The website must clearly communicate:

- whether the pool is operational
- how to connect
- which algorithm is used
- current pool status
- block and payment status

### NFR-019: Professional Presentation

The public site should appear clean, professional, and trustworthy.

### NFR-020: Responsive Design

The public site should remain usable on mobile devices.

### NFR-021: Readable Metrics

Important metrics must be understandable without requiring expert pool
knowledge.

### NFR-022: Share-Derived Metric Labeling

Metrics derived from shares must be clearly labeled as derived from shares and
not blockchain verified.

### NFR-023: Estimated Hashrate Labeling

Estimated hashrate must be clearly presented as a rough estimate based on an
assumed share difficulty until real difficulty-based accounting exists.

---

## 3.5 Security Requirements

### NFR-024: No Public Daemon RPC

PEPEPOWd RPC must not be directly exposed to the public internet.

### NFR-025: No Public Redis Exposure

If Redis is introduced in a future phase, it must not be directly exposed
publicly.

### NFR-026: Minimal Wallet Exposure

Wallet-related operations must be isolated and minimized.

### NFR-027: Public Surface Minimization

Only necessary public ports and services should be exposed.

### NFR-028: Rate Limiting / Basic Hardening

The public web layer should support basic hardening such as rate limiting and
service isolation.

### NFR-029: Payment Traceability

Future payment actions must be logged or otherwise auditable.

---

## 4. Data Requirements

## 4.1 Pool Data

The current system should track and/or expose:

- pool hashrate derived from shares
- active miners
- active workers
- fee
- minimum payout threshold as configuration metadata
- worker distribution
- rolling windows for `1m`, `5m`, `15m`

Future full-pool work may additionally expose:

- effort or luck metrics
- recent rounds summary

## 4.2 Network Data

The system should track and/or expose:

- current chain height
- current difficulty
- network hashrate if available
- block interval indicators
- daemon connectivity / sync status

## 4.3 Block Data

The system should track and/or expose:

- block height
- block hash where available
- found time
- observed state
- reward information where applicable

## 4.4 Miner Data

The current system should track and/or expose:

- wallet address
- miner-level estimated hashrate
- per-wallet share count
- workers
- worker hashrate
- per-worker share count
- rolling windows for `1m`, `5m`, `15m`
- last share time

Future full-pool work may additionally expose:

- pending balance
- total paid
- recent payments

---

## 5. Operational Constraints

### OC-001: Single-Host First

The initial deployment must work on a single host.

### OC-002: Shared Resource Awareness

The solution must assume possible coexistence with other PEPEPOW services on
the same machine or ecosystem.

### OC-003: No Over-Engineering

The design must avoid unnecessary abstraction for future scenarios not required
by the current round.

### OC-004: Stability Before Polish

Correct pool behavior is more important than advanced visuals.

### OC-005: Conservative Payout Operations

Payment automation should be introduced cautiously and only after correctness
is validated.

---

## 6. Development Process Requirements for AI Agents

### DPR-001: Small, Reviewable Changes

Each development iteration should be limited to a manageable scope.

### DPR-002: Change Reporting

Each change set should include:

- files modified
- purpose
- risks
- verification steps

### DPR-003: Core Before UI

Core mining correctness must come before frontend polish.

### DPR-004: Avoid Unnecessary Large Refactors

Working modules should not be broadly rewritten without clear benefit.

### DPR-005: Keep Docs Updated

Any new dependency, service, configuration, or script must be documented.

---

## 7. Acceptance Criteria

## 7.1 Current Round Acceptance

The current round is acceptable when:

- miners can connect to the Stratum endpoint
- submitted shares are ingested
- share records are maintained by wallet and worker
- the API shows live miner activity from the activity snapshot overlay
- the public API contract remains stable
- services can restart and recover
- the system remains stable under load
- deployment and runbook steps are documented

## 7.2 Pre-Full-Pool Acceptance

Before broader public use as a validated pool, the system should additionally
demonstrate:

- share validation correctness
- block template retrieval
- valid block submission
- correct handling of immature/orphan/confirmed states
- payout accounting correctness
- payment workflow traceability
- logging and rollback paths available
- basic hardening in place

---

## 8. Explicit Avoidances

The current system should avoid:

- multi-coin pool architecture
- auto-exchange payout systems
- large database/reporting complexity
- direct frontend-to-daemon integrations
- large account/auth systems
- premature generic abstraction
- high-cost real-time analytics on small hardware

---

## 9. Priority Order for Decisions

When requirements conflict, resolve them in this order:

1. correctness
2. stability
3. simplicity
4. maintainability
5. observability
6. performance efficiency
7. visual polish
