# PEPEPOW Community Pool Requirements

## Purpose

This document defines the functional and non-functional requirements for the PEPEPOW community mining pool project.

The goal is to create a lightweight, maintainable, ARM64-compatible, single-coin pool suitable for:

- learning pool operations
- supporting the PEPEPOW community
- public or limited public mining use
- iterative AI-agent-assisted development

---

## 1. Project Scope

### In Scope
- PEPEPOW-only mining pool
- hoohash-pepew / hoohashv110-pepew support
- public-facing mining website
- basic stratum functionality
- share accounting
- block tracking
- payout accounting
- miner wallet lookup
- basic pool stats and network stats
- deployable on Oracle Cloud ARM64 small instance

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

## 2.1 Core Mining Requirements

### FR-001: Miner Connectivity
The pool must provide at least one public stratum endpoint that miners can connect to.

### FR-002: Share Submission
The pool must accept valid shares from miners and reject invalid ones.

### FR-003: Share Accounting
The pool must track shares by wallet and worker.

### FR-004: Block Template Retrieval
The pool must retrieve valid block templates from the PEPEPOW daemon.

### FR-005: Candidate Block Handling
The pool must be able to process valid shares that form a candidate block.

### FR-006: Block Submission
The pool must submit valid candidate blocks to the PEPEPOW daemon.

### FR-007: Block State Tracking
The pool must track block lifecycle states, including at minimum:
- pending
- immature
- confirmed
- orphan

### FR-008: Miner Identity Model
Miner identity must be wallet-address-based in the initial version.

### FR-009: Worker Visibility
The system must distinguish workers under the same wallet when possible.

---

## 2.2 Pool Accounting Requirements

### FR-010: Round Tracking
The pool must track mining rounds associated with found blocks.

### FR-011: Payout Scheme
The initial system must support one payout model only, preferably PPLNS.

### FR-012: Balance Tracking
The system must track pending and payable balances by wallet.

### FR-013: Minimum Payout Threshold
The system must support a minimum payout threshold.

### FR-014: Payment History
The system must track and display payment history by wallet.

### FR-015: Manual or Semi-Automated Payout Support
The initial version may use manual or semi-automated payout flow, but payment actions must be traceable.

### FR-016: Payout Safety
The system must not treat immature or orphaned blocks as eligible for payout.

---

## 2.3 Stats and API Requirements

### FR-017: Pool Summary API
The system must provide an API endpoint for summary pool statistics.

### FR-018: Network Summary API
The system must provide an API endpoint for basic network statistics.

### FR-019: Miner Lookup API
The system must provide an API endpoint for wallet-based miner lookup.

### FR-020: Blocks API
The system must provide an API endpoint for recent blocks and their states.

### FR-021: Payments API
The system must provide an API endpoint for recent payments.

### FR-022: Worker Summary API
The system should provide worker-level summary data where available.

### FR-023: Cache-Friendly API
The public API should return pre-aggregated or cacheable data rather than triggering heavy live recalculation.

---

## 2.4 Frontend Requirements

### FR-024: Public Website
The project must provide a public website.

### FR-025: Landing Page
The site must have a landing page describing the pool and connection information.

### FR-026: Mining Connection Instructions
The site must provide clear connection instructions including:
- algorithm
- stratum endpoint
- example command lines
- wallet usage conventions
- worker naming conventions if supported

### FR-027: Pool Dashboard
The site must provide a dashboard for pool-level summary data.

### FR-028: Blocks Page
The site must provide a page listing recent blocks and statuses.

### FR-029: Payments Page
The site must provide a page listing recent payments.

### FR-030: Miner Lookup Page
The site must provide a wallet lookup page.

### FR-031: Status or Notice Visibility
The site should provide a way to display maintenance notices, upgrade notices, or service status.

### FR-032: Copy-Friendly Commands
Mining commands and pool addresses should be easy to copy.

---

## 2.5 Operations Requirements

### FR-033: systemd Service Management
Major components must be operable as systemd services or equivalent persistent services.

### FR-034: Reverse Proxy
The site and API should be served behind nginx or an equivalent reverse proxy.

### FR-035: TLS
Public web access should support HTTPS.

### FR-036: Logging
Major components must produce logs sufficient for troubleshooting.

### FR-037: Restart Recovery
The system must recover from service restarts without manual reconstruction of core state.

### FR-038: Deployment Documentation
The project must include documentation sufficient to reproduce deployment on a fresh server.

### FR-039: Configuration Documentation
Key configuration files and environment variables must be documented.

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
The initial implementation should prefer lightweight components over heavy infrastructure.

---

## 3.2 Maintainability Requirements

### NFR-006: AI-Agent-Friendly Structure
The codebase must be organized so that AI agents can modify subsystems with limited blast radius.

### NFR-007: Small-Step Changeability
The system should support incremental feature development and safe refactoring.

### NFR-008: Clear File and Service Boundaries
Service ownership and code boundaries must be understandable.

### NFR-009: Config Clarity
Configurations should be explicit, readable, and commented when practical.

### NFR-010: Reproducibility
A new environment should be able to reproduce the deployment from documentation and repository contents.

---

## 3.3 Compatibility Requirements

### NFR-011: ARM64 Compatibility
All chosen components and dependencies must be reviewed for ARM64 / aarch64 compatibility.

### NFR-012: Ubuntu / systemd Compatibility
The deployment target should assume Ubuntu with systemd.

### NFR-013: PEPEPOW Compatibility
The system must be compatible with the current PEPEPOW daemon, chain state, and supported miner connection expectations.

---

## 3.4 Usability Requirements

### NFR-014: Clear Information Hierarchy
The website must clearly communicate:
- whether the pool is operational
- how to connect
- which algorithm is used
- current pool status
- block and payment status

### NFR-015: Professional Presentation
The public site should appear clean, professional, and trustworthy.

### NFR-016: Responsive Design
The public site should remain usable on mobile devices.

### NFR-017: Readable Metrics
Important metrics must be understandable without requiring expert pool knowledge.

---

## 3.5 Security Requirements

### NFR-018: No Public Daemon RPC
PEPEPOWd RPC must not be directly exposed to the public internet.

### NFR-019: No Public Redis Exposure
Redis must not be directly exposed publicly.

### NFR-020: Minimal Wallet Exposure
Wallet-related operations must be isolated and minimized.

### NFR-021: Public Surface Minimization
Only necessary public ports and services should be exposed.

### NFR-022: Rate Limiting / Basic Hardening
The public web layer should support basic hardening such as rate limiting and service isolation.

### NFR-023: Payment Traceability
Payment actions must be logged or otherwise auditable.

---

## 4. Data Requirements

## 4.1 Pool Data
The system should track and/or expose:
- pool hashrate
- active miners
- active workers
- pool fee
- minimum payout threshold
- effort or luck metrics if available
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
- state
- reward information where applicable

## 4.4 Miner Data
The system should track and/or expose:
- wallet address
- miner-level estimated hashrate
- workers
- worker hashrate
- last share time
- pending balance
- total paid
- recent payments

---

## 5. Operational Constraints

### OC-001: Single-Host First
The initial deployment must work on a single host.

### OC-002: Shared Resource Awareness
The solution must assume possible coexistence with other PEPEPOW services on the same machine or ecosystem.

### OC-003: No Over-Engineering
The design must avoid unnecessary abstraction for future scenarios not required by MVP.

### OC-004: Stability Before Polish
Correct pool behavior is more important than advanced visuals.

### OC-005: Conservative Payout Operations
Payment automation should be introduced cautiously and only after correctness is validated.

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

## 7.1 MVP Acceptance
The MVP is acceptable when:

- miners can connect to the stratum endpoint
- valid shares are accepted
- share records are maintained
- block templates are retrieved
- valid blocks can be submitted
- basic pool/network/miner information is viewable on the website
- services can restart and recover
- deployment steps are documented

## 7.2 Pre-Public-Use Acceptance
Before broader public use, the system should additionally demonstrate:

- payout accounting correctness
- correct handling of immature/orphan/confirmed states
- basic website reliability
- basic hardening in place
- logging and rollback paths available
- payment workflow traceability

---

## 8. Explicit Avoidances

The initial system should avoid:

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