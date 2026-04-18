# PEPEPOW Community Pool Deployment Plan

## Purpose

This document defines the deployment strategy for the PEPEPOW community pool
stack.

The goal is to deploy a lightweight, maintainable, reproducible stack on a
small Oracle Cloud ARM64 instance while minimizing operational risk and keeping
the baseline share-ingest path available while progressively enabling validated
mining milestones.

---

## 1. Deployment Objectives

The deployment must achieve the following:

- run on Oracle Cloud
- support ARM64 / aarch64
- remain operable on 1 vCPU / 6 GB RAM
- expose a public mining endpoint
- expose a public website
- keep daemon RPC and internal services private
- remain easy to maintain and rebuild
- support AI-agent-assisted iteration
- support staged mining progression:
  - baseline ingest
  - validation
  - candidate dry-run
  - controlled submission

---

## 2. Target Environment

### Infrastructure

- Oracle Cloud VM
- ARM64 / aarch64
- Ubuntu
- systemd
- public IP
- domain or subdomain for the pool website

### Initial Deployment Model

Single-host deployment.

The current services expected to run on the same VM are:

- `PEPEPOWd`
- pool-core snapshot producer
- Stratum ingress
- template-backed validation path inside pool core
- public API
- frontend
- nginx

Optional later services:

- isolated submission helper if ever needed
- payout worker
- notification worker
- Redis only if clearly justified

This model is chosen because it is simpler, lighter, and easier to manage at
the current scale.

---

## 3. Deployment Principles

### 3.1 Simplicity First

Use the minimum number of services required to achieve a working public mining
endpoint and website.

### 3.2 Reproducibility

A fresh server should be able to reproduce the environment from documented
steps.

### 3.3 Isolation of Sensitive Services

Internal services must not be publicly exposed unless explicitly intended.

### 3.4 Safe Iteration

Deployments should support small changes, verification, and rollback.

### 3.5 Low Resource Awareness

Polling frequency, service count, and frontend behavior must be chosen
carefully for a 1-core machine.

### 3.6 Feature Gating

Higher-risk mining features, especially real block submission, must remain
separately gateable and disabled by default.

---

## 4. Proposed Runtime Layout

## Public-Facing Components

- nginx
- frontend
- public stats/API endpoints
- Stratum endpoint

## Private/Internal Components

- PEPEPOWd RPC
- runtime snapshot producer internals
- activity snapshot file
- template-backed validation internals
- candidate dry-run outputs
- any real submission tooling
- any payout tooling
- any admin-only scripts or maintenance tools
- optional future Redis

---

## 5. Suggested Host Layout

A possible filesystem layout:

- `/opt/pepepow-pool/`
  - application code
- `/opt/pepepow-pool/config/`
  - environment and config files
- `/opt/pepepow-pool/scripts/`
  - operational scripts
- `/var/log/pepepow-pool/`
  - service-specific logs if not using journald only
- `/var/lib/pepepow-pool/`
  - runtime snapshot
  - activity snapshot
  - share log
  - candidate-prep / dry-run artifacts where enabled
- daemon data directory

Optional later paths:

- payout state or reporting data
- Redis data/config

---

## 6. Deployment Phases

## Phase 0: Pre-Deployment Review

Before any installation begins, confirm:

- all major dependencies are ARM64-compatible
- daemon version matches current PEPEPOW network requirements
- domain/subdomain plan is decided
- firewall/public port policy is decided
- backup approach is defined
- current round scope is understood:
  - baseline share ingest is working
  - daemon-template-backed validation is in scope
  - candidate dry-run is in scope
  - real block submission is controlled and disabled by default
  - payouts are not yet in scope

### Deliverables

- dependency review
- service inventory
- network exposure plan
- configuration variable list
- feature-flag plan for higher-risk mining stages

---

## Phase 1: Base Host Preparation

Prepare the server for deployment.

### Tasks

- create deployment user where appropriate
- update system packages
- install required OS packages
- configure timezone if needed
- ensure systemd availability
- create directory structure
- prepare firewall rules
- install nginx
- install runtime dependencies for the current stack
- prepare TLS certificate plan

Optional later tasks:

- install Redis

### Validation

- system updated successfully
- required packages installed
- directories created
- basic firewall policy applied
- nginx starts successfully

---

## Phase 2: Daemon Deployment

Deploy `PEPEPOWd` and ensure chain compatibility for the runtime snapshot
producer and template-backed mining path.

### Tasks

- install or deploy `PEPEPOWd` binary
- configure data directory
- configure RPC to bind privately
- configure credentials securely
- start daemon with systemd
- confirm sync status
- confirm RPC works locally only

### Validation

- daemon starts on boot
- local RPC responds
- node is synced or syncing correctly
- daemon is not exposed publicly
- logs are readable

### Notes

Baseline Stratum ingress observability should not fully depend on daemon health.
Daemon health still matters for runtime chain snapshots and validation
progression.

---

## Phase 3: Baseline Pool Core Deployment

Deploy the baseline currently implemented pool-core services.

### Tasks

- deploy pool-core code
- configure PEPEPOW coin settings and public Stratum metadata
- configure `stratum_ingress.py`
- configure bind host and bind port
- configure share log path
- configure activity snapshot output path
- configure queue size
- configure activity snapshot interval
- configure `producer.py` runtime snapshot output path
- configure daemon RPC only for runtime snapshot producer and later validation
- run `pepepow-pool-stratum.service` as a dedicated systemd service
- run `pepepow-pool-core.service` as a dedicated systemd service when chain
  snapshots are desired

### Validation

- Stratum service starts successfully
- Stratum port listens correctly
- miner can connect
- `mining.subscribe`, `mining.authorize`, and `mining.submit` succeed
- submitted shares are appended to JSONL
- activity snapshot updates
- no crash or blocking under burst load
- service restarts cleanly

### Notes

This phase establishes the safe baseline and must remain recoverable even if
later mining-validation features are not enabled.

---

## Phase 3.5: Validated Mining Bring-Up

Enable the current in-progress mining milestone without yet enabling broad
production submission behavior.

### Tasks

- configure daemon-template-backed job flow
- verify template retrieval
- enable or deploy share validation logic
- verify pool share vs block candidate split
- configure candidate artifact output path if needed
- configure no-send / dry-run behavior
- ensure real submission flag remains disabled by default
- verify validation and dry-run logging

### Validation

- block templates are retrieved successfully
- submitted shares are classified correctly
- valid pool shares are distinguishable from block candidates
- ordinary valid shares do not enter candidate-prep path
- block-target shares do enter candidate-prep path
- dry-run payload or candidate artifact is produced correctly
- no real submit occurs while submit flag is off
- services remain stable under restart

### Notes

This phase is the current operational bridge between baseline ingress and later
controlled block submission.

---

## Phase 3.6: Controlled Submit Hook Enablement

Enable real submission only as an explicitly operator-controlled milestone.

### Tasks

- introduce or configure explicit submit-enable flag
- verify default state is disabled
- verify logging of submission attempt metadata
- verify logging of daemon response
- verify rollback / disable path
- keep scope limited to controlled testing

### Validation

- no real submission occurs when disabled
- real submission occurs only when explicitly enabled
- submission results are recorded clearly
- disable / rollback can be performed quickly
- daemon RPC remains private
- feature does not destabilize baseline services

### Notes

This phase is not the same as production-ready full-pool operation. It is a
controlled milestone for correctness verification.

---

## Phase 4: Stats/API Deployment

Deploy the API layer that feeds the frontend.

### Tasks

- deploy lightweight API service
- expose pool summary endpoints
- expose network summary endpoints
- expose blocks endpoints
- expose payments endpoints
- expose miner lookup endpoints
- configure runtime snapshot path
- configure fallback snapshot path
- configure optional activity snapshot overlay path
- later optionally expose summarized validation/candidate states where useful
- route through nginx if public

### Validation

- API returns expected JSON
- API does not directly expose daemon internals
- API can serve fallback chain data plus live activity overlay
- repeated requests do not cause expensive raw log parsing
- service restarts cleanly

---

## Phase 5: Frontend Deployment

Deploy the public website.

### Tasks

- deploy frontend app or static site
- connect frontend to stats/API
- build landing page
- build dashboard page
- build blocks page
- build payments page
- build miner lookup page
- build connect/how-to-mine page
- add notices/status support
- ensure responsive behavior

### Validation

- site loads correctly
- core pages work
- commands are copyable
- wallet lookup works
- site remains usable on mobile
- visual hierarchy is clear

### Notes

Frontend should not depend on raw daemon RPC and should consume only safe,
summarized API outputs.

---

## Phase 6: Reverse Proxy and TLS

Publish the service through nginx.

### Tasks

- configure domain/subdomain
- configure reverse proxy routing
- configure HTTPS
- configure HTTP to HTTPS redirect if desired
- configure caching headers where appropriate
- configure rate limiting/basic hardening
- separate web/API routing from internal-only services

### Validation

- HTTPS works
- public site is accessible
- public API is accessible as intended
- Stratum port is publicly reachable if intended
- daemon RPC remains private
- rate limiting/basic protection is functional

---

## Phase 7: Block State and Round Tracking

Not yet part of the current controlled mining milestone. Enable only after
submission correctness is credible.

### Tasks

- define block lifecycle states
- track pending / immature / confirmed / orphan transitions
- associate found candidates with later block outcomes
- define round boundaries conservatively

### Validation

- block state transitions are coherent
- orphan handling is correct
- immature blocks are not treated as payable
- round tracking is auditable

---

## Phase 8: Payout Workflow Enablement

Not part of the current deployable scope. Enable payment operations only after
validated mining and block-state correctness are confirmed.

### Tasks

- validate accounting logic
- validate block maturity handling
- define payment threshold
- implement manual or semi-automated payout process
- log payment actions
- verify wallet exposure remains minimal

### Validation

- payment candidates are correct
- immature/orphan blocks do not pay
- payment action logs exist
- payout flow is understandable and recoverable

---

## Phase 9: Operations Hardening

Add baseline operational safety features.

### Tasks

- configure logrotate if needed
- confirm journald visibility
- add backup scripts
- document restore steps
- add service health checks
- add maintenance-mode or status notices
- optionally add Discord/Telegram notifications

### Validation

- logs are accessible
- backups run successfully
- restore procedure is documented
- health checks are usable
- common failures are diagnosable

---

## 7. Public Exposure Plan

## Required Public Exposure

- website (HTTPS)
- public stats/API endpoints
- one Stratum port

## Must Not Be Public

- daemon RPC
- internal scripts
- raw candidate-prep internals
- real submission admin tooling
- payout admin tooling
- raw internal configs
- optional future Redis

---

## 8. Firewall and Port Planning

Actual port numbers may vary depending on implementation, but the policy should
be:

### Allow Public

- `80/tcp` only if needed for redirect or certificate flow
- `443/tcp` for website/API
- configured Stratum port for miners

### Internal Only

- daemon RPC port
- API bind port if proxied privately
- any internal app port not meant for public proxying
- any real submission admin-only path
- optional future Redis port

### Notes

Public exposure must be justified service by service. Default-deny is preferred
where practical.

---

## 9. Configuration Management Plan

Configuration should be split clearly between:

- environment variables
- service configs
- nginx configs
- daemon config
- pool config
- frontend runtime config
- mining feature flags

Optional later config groups:

- payout config
- Redis config

### Rules

- secrets must not be hardcoded into source files
- config names must be documented
- defaults should be sane and conservative
- higher-risk flags must default to disabled
- comments should be added where helpful

---

## 10. systemd Service Plan

Each long-running component should have a dedicated systemd service where
practical.

Current services:

- `pepepowd.service`
- `pepepow-pool-core.service`
- `pepepow-pool-stratum.service`
- `pepepow-pool-api.service`
- `pepepow-pool-frontend.service`

Optional later services:

- isolated submission helper
- payout worker
- notification worker
- Redis

### Service Rules

- restart policy should be defined
- service user should be explicit where practical
- working directory should be explicit
- environment file usage should be documented
- logs should be inspectable

### Snapshot Ownership Notes

- `pepepow-pool-core.service` owns `pool-snapshot.json`
- `pepepow-pool-stratum.service` owns `share-events.jsonl` and
  `activity-snapshot.json`
- candidate-prep / dry-run artifacts should have clearly documented ownership if
  stored on disk
- API reads runtime snapshot first, fallback snapshot second, and applies the
  optional activity snapshot overlay

---

## 11. Logging Plan

Logs must support troubleshooting in these categories:

- daemon sync/connectivity problems
- runtime snapshot producer failures
- miner connection/share failures
- activity snapshot failures
- template retrieval failures
- validation failures
- candidate-prep failures
- dry-run preparation failures
- controlled submission failures
- API failures
- frontend serving failures
- nginx proxy/TLS issues
- later payout failures

### Preferred Approach

- journald for service logs
- optional file logs for components that benefit from them
- logrotate for file-based logs

---

## 12. Backup and Recovery Plan

The deployment plan must include backup considerations for:

- daemon wallet or wallet-related sensitive state
- application configuration
- runtime snapshot and activity snapshot configuration
- environment files
- nginx configuration
- custom scripts
- candidate-prep or dry-run config where relevant

Later full-pool backup considerations:

- payment/accounting records if not reconstructable

### Recovery Goals

- rebuild on a fresh host
- restore configuration
- restore wallet-sensitive material securely
- restore service startup order
- recover website and mining functionality

### Recovery Documentation

At minimum, document:

- what must be backed up
- where it lives
- how to restore it
- what must never be publicly exposed during restore

---

## 13. Rollback Strategy

Every major deployment step should have a rollback path.

### Examples

- keep previous app release available
- keep previous nginx config backup
- keep previous systemd unit backup
- keep higher-risk flags disabled until validation passes
- separate storage/schema changes where possible
- validate before switching traffic

### Rollback Principles

- rollback should be possible without guesswork
- changes should be incremental
- large refactors should not be deployed without validation checkpoints

---

## 14. Validation Checklist by Stage

## Base Host

- OS updated
- required packages installed
- firewall baseline configured
- nginx healthy

## Daemon

- starts successfully
- local RPC works
- sync state acceptable
- not publicly exposed

## Baseline Pool Core

- Stratum service starts successfully
- miner connects
- share flow works
- activity snapshot updates
- API overlay works

## Validated Mining Bring-Up

- template retrieval works
- share validation works
- valid pool shares are distinguished from block candidates
- candidate-prep works
- dry-run output is correct
- submit flag remains off by default

## Controlled Submit Hook

- disabled state blocks real submission
- enabled state allows controlled submission
- result logging works
- rollback / disable path works

## API

- returns correct data
- remains lightweight
- does not over-query daemon
- does not parse raw JSONL logs on request paths

## Frontend

- pages render
- wallet lookup works
- key info is clear
- responsive behavior acceptable

## Public Access

- HTTPS works
- public routes correct
- internal services remain private

## Later Full-Pool Validation

- block states are correct
- payout thresholds are correct
- payment flow is logged
- immature/orphan protection works

## Recovery

- restart works
- backup exists
- restore process documented

## Benchmark Guidance

Current stress tests and benchmark examples are documented separately and should
be treated as historical reference for baseline ingress performance.

---

## 15. Resource Management Guidance

Because the host has only 1 core / 6 GB RAM:

- keep service count low
- avoid unnecessary background jobs
- keep dashboard refresh conservative
- avoid heavy charting backends
- avoid large databases unless clearly necessary
- prefer summarized metrics to expensive real-time analytics
- keep template refresh and validation overhead bounded
- avoid high-frequency daemon polling when equivalent cached or retained state
  is sufficient

If the host also runs other PEPEPOW services, resource contention must be
considered before expanding features.

---

## 16. Post-MVP Deployment Expansion

Only after stable current deployment, consider:

- richer validated mining flow
- round / block-state tracking improvements
- payout accounting and controlled payouts
- richer miner metrics
- notifications and status integrations
- better admin tooling
- separated API/frontend hosts
- split Stratum and web workloads further
- stronger alerting and incident tooling

These remain secondary to core correctness and safe operation.

---

## 17. Final Deployment Goal

### Current Deployable Goal

The current deployment is successful when:

- a PEPEPOW miner can connect and submit shares
- shares are ingested into JSONL
- activity snapshots are updated
- template-backed validation path can be brought up
- candidate dry-run can be performed safely
- real submission remains operator-controlled
- the website exposes pool/network/miner information
- services recover cleanly after restart
- internal services remain protected
- documentation is sufficient to reproduce the environment

### Later Full-Pool Goal

The later full-pool deployment will be successful when:

- the pool tracks block states correctly
- payout correctness is demonstrable
- the system is stable enough for broader controlled community use

---

## 18. Decision Priority Order

When deployment decisions conflict, prioritize:

1. safe operation
2. core correctness
3. simplicity
4. maintainability
5. reproducibility
6. performance optimization
7. visual enhancement

---

## 19. Current Skeleton Deliverables

This repository currently includes deployment skeletons and baseline public
stack support for:

- nginx
- static frontend service
- lightweight API service
- Stratum ingress
- daemon-aware runtime snapshot path

The repository should now be understood as supporting progression toward:

- template-backed validation
- candidate preparation
- dry-run submission
- controlled real submission

The current private-only assumptions remain:

- daemon RPC is not proxied publicly
- real submission must remain controlled
- payout tooling is not exposed
- Redis is optional later infrastructure, not a current dependency