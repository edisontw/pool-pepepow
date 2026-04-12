# PEPEPOW Community Pool Deployment Plan

## Purpose

This document defines the deployment strategy for the initial PEPEPOW community pool.

The goal is to deploy a lightweight, maintainable, reproducible pool stack on a small Oracle Cloud ARM64 instance while minimizing operational risk and unnecessary complexity.

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

This means the following services are expected to run on the same VM initially:

- PEPEPOWd
- Redis
- pool core
- stats/API
- frontend
- nginx

This model is chosen because it is simpler, lighter, and easier to manage at the current scale.

---

## 3. Deployment Principles

### 3.1 Simplicity First
Use the minimum number of services required to achieve a working pool.

### 3.2 Reproducibility
A fresh server should be able to reproduce the environment from documented steps.

### 3.3 Isolation of Sensitive Services
Internal services must not be publicly exposed unless explicitly intended.

### 3.4 Safe Iteration
Deployments should support small changes, verification, and rollback.

### 3.5 Low Resource Awareness
Polling frequency, service count, and frontend behavior must be chosen carefully for a 1-core machine.

---

## 4. Proposed Runtime Layout

## Public-Facing Components
- nginx
- frontend
- public stats/API endpoints
- stratum endpoint(s)

## Private/Internal Components
- PEPEPOWd RPC
- Redis
- any payout tooling
- any admin-only scripts or maintenance tools

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
  - persistent app data if needed
- daemon data directory
- Redis data/config as appropriate

The exact layout may vary, but it should remain explicit and documented.

---

## 6. Deployment Phases

## Phase 0: Pre-Deployment Review

Before any installation begins, confirm:

- chosen pool core is compatible with PEPEPOW requirements
- all major dependencies are ARM64-compatible
- daemon version matches current PEPEPOW network requirements
- domain/subdomain plan is decided
- firewall/public port policy is decided
- wallet/payout operational policy is decided
- backup approach is defined

### Deliverables
- dependency review
- service inventory
- network exposure plan
- configuration variable list

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
- install runtime dependencies for chosen stack
- install Redis
- prepare TLS certificate plan

### Validation
- system updated successfully
- required packages installed
- directories created
- basic firewall policy applied
- nginx starts successfully
- Redis starts successfully

---

## Phase 2: Daemon Deployment

Deploy PEPEPOWd and ensure chain compatibility.

### Tasks
- install or deploy PEPEPOWd binary
- configure data directory
- configure RPC to bind privately
- configure credentials securely
- start daemon with systemd
- confirm sync status
- confirm RPC works locally only
- confirm wallet behavior and payout policy assumptions

### Validation
- daemon starts on boot
- local RPC responds
- node is synced or syncing correctly
- daemon is not exposed publicly
- logs are readable

### Notes
This phase must be stable before pool-core work proceeds.

---

## Phase 3: Pool Core Deployment

Deploy the mining pool engine.

### Tasks
- deploy pool core code
- configure PEPEPOW coin settings
- configure algorithm settings
- configure Redis connectivity
- configure daemon RPC integration
- configure stratum endpoint
- configure vardiff/basic miner policies
- run as dedicated systemd service

### Validation
- pool core starts successfully
- stratum port listens correctly
- miner can connect
- valid shares are accepted
- invalid shares are rejected
- basic stats are generated
- service restarts cleanly

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
- add caching or pre-aggregation
- route through nginx if public

### Validation
- API returns expected JSON
- API does not directly expose daemon internals
- repeated requests do not cause excessive daemon load
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
- daemon RPC remains private
- Redis remains private
- rate limiting/basic protection is functional

---

## Phase 7: Payout Workflow Enablement

Enable payment operations only after mining correctness is confirmed.

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

## Phase 8: Operations Hardening

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
- one or more stratum ports

## Must Not Be Public
- daemon RPC
- Redis
- internal scripts
- payout admin tooling
- raw internal configs

---

## 8. Firewall and Port Planning

Actual port numbers may vary depending on implementation, but the policy should be:

### Allow Public
- 80/tcp only if needed for redirect or certificate flow
- 443/tcp for website/API
- stratum port(s) for miners

### Internal Only
- daemon RPC port
- Redis port
- any internal app port not meant for public proxying

### Notes
Public exposure must be justified service by service.  
Default-deny is preferred where practical.

---

## 9. Configuration Management Plan

Configuration should be split clearly between:

- environment variables
- service configs
- nginx configs
- daemon config
- Redis config
- pool config
- frontend build/runtime config

### Rules
- secrets must not be hardcoded into source files
- config names must be documented
- defaults should be sane and conservative
- comments should be added where helpful

---

## 10. systemd Service Plan

Each long-running component should have a dedicated systemd service where practical.

Potential services:

- `pepepowd.service`
- `pepepow-pool.service`
- `pepepow-pool-api.service`
- `pepepow-pool-frontend.service`

Optional:
- periodic stats collector
- payout worker
- notification worker

### Service Rules
- restart policy should be defined
- service user should be explicit where practical
- working directory should be explicit
- environment file usage should be documented
- logs should be inspectable

---

## 11. Logging Plan

Logs must support troubleshooting in these categories:

- daemon sync/connectivity problems
- pool core startup failures
- miner connection/share failures
- block submission failures
- payout failures
- API failures
- frontend serving failures
- nginx proxy/TLS issues

### Preferred Approach
- journald for service logs
- optional file logs for components that benefit from them
- logrotate for file-based logs

---

## 12. Backup and Recovery Plan

The deployment plan must include backup considerations for:

- daemon wallet or wallet-related sensitive state
- application configuration
- payment/accounting records if not reconstructable
- nginx configuration
- environment files
- custom scripts

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
- separate schema or storage changes where possible
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
- nginx and Redis healthy

## Daemon
- starts successfully
- local RPC works
- sync state acceptable
- not publicly exposed

## Pool Core
- starts successfully
- miner connects
- share flow works
- block template retrieval works

## API
- returns correct data
- remains lightweight
- does not over-query daemon

## Frontend
- pages render
- wallet lookup works
- key info is clear
- responsive behavior acceptable

## Public Access
- HTTPS works
- public routes correct
- internal services remain private

## Payout
- thresholds correct
- payment flow logged
- immature/orphan protection works

## Recovery
- restart works
- backup exists
- restore process documented

---

## 15. Resource Management Guidance

Because the host has only 1 core / 6 GB RAM:

- keep service count low
- avoid unnecessary background jobs
- keep dashboard refresh conservative
- avoid heavy charting backends
- avoid large databases unless clearly necessary
- prefer summarized metrics to expensive real-time analytics

If the host also runs other PEPEPOW services, resource contention must be considered before expanding features.

---

## 16. Post-MVP Deployment Expansion

Only after stable MVP deployment, consider:

- improved visual analytics
- richer miner metrics
- notifications and status integrations
- better admin tooling
- separated API/frontend hosts
- split stratum and web workloads
- stronger alerting and incident tooling

These must remain secondary to core pool correctness and safe operation.

---

## 17. Final Deployment Goal

The deployment is considered successful when the following are true:

- a PEPEPOW miner can connect and submit shares
- the pool can retrieve templates and submit valid blocks
- the website clearly exposes pool/network/miner information
- services recover cleanly after restart
- internal services remain protected
- documentation is sufficient to reproduce the environment
- the system is stable enough for controlled community use

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