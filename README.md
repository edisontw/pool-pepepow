# pool-pepepow

PEPEPOW-only community pool implementation for a single operator-managed Ubuntu host.

The current project provides a public static website, a read-only public API, active
Stratum ingress, daemon-template-backed mining, candidate follow-up, controlled
submitblock validation, and payout review tooling. Manual payment records are public.
A private operator-owned auto wallet payout self-test exists, but this is not public automatic payout readiness.

## Quick Links

- How to deploy: [Quickstart](docs/deploy-pepepow-pool-quickstart.md), [Oracle Ubuntu deployment](docs/oracle-ubuntu-deployment.md), and [deployment plan](docs/deployment-plan.md)
- Architecture: [Architecture](docs/architecture.md)
- API docs: [Public API page](apps/frontend/site/api.html)
- Operations/runbooks: [Runbooks](docs/runbooks/README.md)
- Prelaunch checklist: [docs/runbooks/prelaunch-checklist.md](docs/runbooks/prelaunch-checklist.md)
- Benchmarks/milestones: [Benchmarks](docs/benchmarks/)

## Current Scope

This repository currently includes:

- PEPEPOW-only pool services; no multi-coin support.
- Static frontend that reads the public API only.
- Flask/Waitress public API backed by snapshot files.
- Stratum ingress for PEPEPOW mining clients.
- Daemon-template-backed job path for live mining.
- Candidate handling, follow-up observation, and guarded submitblock tooling.
- Controlled/self-test submitblock path validation.
- Round accounting, payout candidate generation, and manual payment records.
- Private operator-owned auto wallet payout self-test tooling.
- Systemd, nginx, and environment examples for deployment.

This repository does not provide:

- multi-coin pool routing
- exchange payout integration
- user accounts or login
- public daemon RPC
- public wallet RPC
- public admin payout controls
- Redis-backed runtime dependency
- a claim of public automatic payout readiness

Redis is not required for the current deployment model.

## Services

- `apps/frontend/site`
  - static HTML/CSS/JS
  - consumes public `GET /api/*` endpoints only
- `apps/api`
  - Flask + Waitress API
  - reads pool/runtime snapshots and safe sidecar snapshots
  - exposes public read-only status, blocks, payments, miner lookup, and pool-listing compatibility endpoints
- `apps/pool-core`
  - Stratum ingress
  - daemon-template job handling
  - share/activity snapshot generation
  - candidate and follow-up event recording
- `ops/scripts`
  - deployment and operations helpers
  - payout review, carry, preflight, guarded one-shot send, and private auto wallet payout self-test commands
- `ops/systemd` and `ops/nginx`
  - example service and public HTTPS configuration files

## Public And Private Boundaries

Public:

- HTTPS website
- read-only HTTPS API
- Stratum mining endpoint
- public block, miner, and manual payment views
- MiningPoolStats-compatible `/api/stats` and secondary `/api/status`

Private/operator-only:

- daemon RPC
- wallet RPC
- submitblock controls
- payout review and wallet send commands
- admin controls
- runtime snapshots and event logs

The public frontend must not proxy daemon RPC, wallet RPC, payout commands, submit
controls, or admin controls.

## Deployment Docs

Detailed install and operations steps live in `docs/`:

- [docs/oracle-ubuntu-deployment.md](docs/oracle-ubuntu-deployment.md)
- [docs/deploy-pepepow-pool-quickstart.md](docs/deploy-pepepow-pool-quickstart.md)
- [docs/deployment-plan.md](docs/deployment-plan.md)
- [docs/local-development.md](docs/local-development.md)
- [docs/runbooks/snapshot-pipeline.md](docs/runbooks/snapshot-pipeline.md)
- [docs/runbooks/prelaunch-checklist.md](docs/runbooks/prelaunch-checklist.md)
- [docs/runbooks/stratum-activity-ingest.md](docs/runbooks/stratum-activity-ingest.md)
- [docs/runbooks/controlled-live-submitblock.md](docs/runbooks/controlled-live-submitblock.md)
- [docs/runbooks/manual-payout-review.md](docs/runbooks/manual-payout-review.md)

Key milestones:

- [2026-06-05 controlled submitblock success](docs/benchmarks/2026-06-05-controlled-submitblock-success.md)
- [2026-06-09 first auto wallet payout self-test](docs/benchmarks/2026-06-09-first-auto-wallet-payout-self-test.md)

## Verification Commands

Run focused checks for the area being changed:

```bash
./ops/scripts/prelaunch-repo-check.sh
PYTHONPATH=apps/api:ops/scripts python3 -m unittest tests.test_api_endpoints
PYTHONPATH=ops/scripts python3 -m unittest tests.test_payout_accounting
bash -n ops/scripts/*.sh
git diff --check
```

For broader local validation:

```bash
python3 -m unittest discover tests
```
