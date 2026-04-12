# pool-pepepow

## Project Overview

`pool-pepepow` is a PEPEPOW community pool repository. It is designed as a single-coin-first, ARM64-friendly, low-resource-oriented monorepo that remains easy for human contributors and AI agents to understand and modify.

## Goals

- Build a stable PEPEPOW-only community pool foundation.
- Keep the initial system operable on a single low-resource host.
- Separate pool, API, frontend, and ops concerns to reduce coupling.
- Favor clear structure and incremental validation over premature feature depth.

## Initial Scope

- Single coin: PEPEPOW only.
- Algorithm target: `hoohash-pepew` / `hoohashv110-pepew`.
- Single-machine deployment for the MVP phase.
- Runtime planning around `PEPEPOWd`, Redis, pool core, stats/API, frontend, nginx, and systemd.

## Non-Goals

- Multi-coin abstractions in the initial phase.
- Heavy framework adoption just to make the repository look complete.
- Payout automation, account systems, or misleading placeholder product features.
- Public exposure of internal runtime dependencies.

## Target Environment

- Oracle Cloud
- Ubuntu
- ARM64 / aarch64
- systemd-managed services
- Initial host profile: 1 vCPU, 6 GB RAM

## Planned Runtime Components

- `PEPEPOWd` for chain and wallet operations
- Redis for internal pool/state coordination
- pool core for share handling and mining workflow
- stats/API service for controlled data access
- frontend for public pool views
- nginx for reverse proxy and edge routing
- systemd for service supervision

Constraints:

- daemon RPC must not be directly exposed to the public network
- Redis must not be directly exposed to the public network
- frontend must not connect directly to daemon RPC

## Repository Structure

```text
pool-pepepow/
├─ README.md
├─ .gitignore
├─ docs/
│  ├─ requirements.md
│  ├─ architecture.md
│  ├─ deployment-plan.md
│  ├─ decisions/
│  └─ runbooks/
├─ apps/
│  ├─ pool-core/
│  ├─ api/
│  └─ frontend/
├─ ops/
│  ├─ systemd/
│  ├─ nginx/
│  ├─ scripts/
│  └─ env/
├─ config/
│  ├─ examples/
│  └─ coins/
└─ tests/
```

## Development Principles

- Stability first, then simplicity, maintainability, extensibility, and cosmetic features.
- Make small changes and validate incrementally.
- Keep repository structure AI-agent-friendly and easy to reason about.
- Avoid direct frontend-to-daemon coupling.
- Keep stats, API, frontend, and ops boundaries as loose as practical.

## MVP Acceptance Targets

- Repository structure supports incremental implementation without major reorganization.
- Core runtime boundaries are documented clearly enough to avoid unsafe direct exposure.
- Deployment assumptions fit a single ARM64 Ubuntu host with constrained resources.
- Future implementation work can start without introducing premature multi-coin complexity.

## Next Step

Confirm the first implementation slice: pool core candidate approach, minimal API/stats stack, and the deployment path for an ARM64 single-host MVP.
