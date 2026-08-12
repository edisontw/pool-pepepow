# pool-pepepow

PEPEPOW-only community mining pool for a single operator-managed Ubuntu host.

This repository is focused on a lightweight, maintainable PEPEPOW pool stack for
community testing, learning, and public mining. It is intentionally single-coin,
snapshot/API-driven, and suitable for a small ARM64 Oracle Cloud instance.

The current stack includes:

- public static website
- read-only public API
- shared Pool Stratum mining on `39333`
- Pure SOLO Stratum mining on `39334`
- daemon-template-backed mining jobs
- share/activity snapshots
- candidate follow-up and block lifecycle tracking
- guarded production `submitblock`
- Pool round/accounting and payout tooling
- Pure SOLO finder-only payout accounting with a configurable SOLO fee
- scheduled private wallet payout tooling with persistent replay protection
- public Pool and SOLO block/payment/miner views

Daemon RPC, wallet RPC, submit controls, payout controls, raw runtime files, and
operator configuration remain private. Public frontend/API surfaces are read-only
and snapshot-driven.

---

## Status

Current target: **single-coin PEPEPOW community Pool + Pure SOLO production stack**

Operational goals:

- Pool miners connect to `pool.pepepow.net:39333`
- Pure SOLO miners connect to `pool.pepepow.net:39334`
- Pool and SOLO shares, candidates, accounting, and payment records stay isolated
- valid block candidates can be submitted automatically through guarded private daemon RPC
- mature Pool and SOLO payouts can be processed by the private scheduled payout workflow
- public API reads snapshots only
- frontend shows Pool/SOLO status, network, blocks, payments, and miner lookup data
- the stack stays simple enough for 1 vCPU / 6 GB RAM

Not goals:

- multi-coin pool
- exchange payouts
- user accounts
- public admin panel
- public daemon RPC
- public wallet RPC
- Redis dependency
- large analytics backend

---

## Mining Endpoints

```text
Pool Mining
stratum+tcp://pool.pepepow.net:39333

Pure SOLO Mining
stratum+tcp://pool.pepepow.net:39334
```

Pool Mining uses the shared Pool reward/accounting flow.

Pure SOLO attributes a valid block to the authenticated finder and pays that
finder the pool-controlled miner reward after the configured SOLO fee. It does
not claim the finder receives unrelated coinbase allocations.

---

## Quick Links

- Quickstart: [`docs/deploy-pepepow-pool-quickstart.md`](docs/deploy-pepepow-pool-quickstart.md)
- Oracle Ubuntu deployment: [`docs/oracle-ubuntu-deployment.md`](docs/oracle-ubuntu-deployment.md)
- Deployment plan: [`docs/deployment-plan.md`](docs/deployment-plan.md)
- Architecture: [`docs/architecture.md`](docs/architecture.md)
- Local development: [`docs/local-development.md`](docs/local-development.md)
- Runbooks: [`docs/runbooks/README.md`](docs/runbooks/README.md)
- Reward calculator and log maintenance: [`docs/runbooks/reward-calculator-and-log-maintenance.md`](docs/runbooks/reward-calculator-and-log-maintenance.md)
- Prelaunch checklist: [`docs/runbooks/prelaunch-checklist.md`](docs/runbooks/prelaunch-checklist.md)
- Benchmarks and milestones: [`docs/benchmarks/`](docs/benchmarks/)
- Public API page: [`apps/frontend/site/api.html`](apps/frontend/site/api.html)

---

## Repository Layout

```text
apps/
  api/
    Flask/Waitress public API.
    Reads safe snapshots and exposes read-only public endpoints.

  frontend/site/
    Static HTML/CSS/JS public website.
    Consumes public API endpoints only.

  pool-core/
    Stratum ingress, template-backed jobs, share validation,
    activity snapshots, candidate events, and guarded submitblock path.

ops/
  scripts/
    Deployment and operator helpers, candidate lifecycle tracking,
    Pool/SOLO payout generation, replay guards, and scheduled payout commands.

  systemd/
    systemd units for Pool/SOLO Stratum and supporting services.

  nginx/
    HTTPS/static frontend/API reverse-proxy examples.

docs/
  Deployment docs, architecture notes, runbooks, benchmarks, and milestones.

tests/
  Focused tests for API, Stratum, Pool/SOLO accounting, payout, and ops behavior.
```

---

## Public Surface

Public components:

- HTTPS website
- read-only HTTPS API
- Pool Stratum `39333`
- Pure SOLO Stratum `39334`
- Pool/SOLO block views
- Pool/SOLO miner lookup
- recorded Pool/SOLO payment history
- MiningPoolStats-compatible `/api/stats`
- secondary `/api/status`

Private/operator-only components:

- daemon RPC
- wallet RPC
- submitblock configuration/controls
- payout configuration/controls
- wallet send commands
- raw runtime snapshots
- raw event logs

The frontend must never call daemon RPC, wallet RPC, submit tooling, payout
commands, raw JSONL files, or internal runtime files.

---

## Current Public API

Common Pool endpoints:

```text
GET /api/health
GET /api/pool/summary
GET /api/network/summary
GET /api/blocks
GET /api/payments
GET /api/miner/<wallet>
GET /api/stats
GET /api/status
```

Pure SOLO endpoints:

```text
GET /api/solo/summary
GET /api/solo/accepted-candidates
GET /api/solo/payments
GET /api/solo/miner/<wallet>
```

API rules:

- public endpoints are read-only
- request paths read snapshots or summaries
- no public endpoint parses large raw runtime logs
- no endpoint exposes daemon RPC, wallet RPC, submit controls, or payout controls
- malformed or missing snapshots degrade safely

---

## Frontend Rules

The website is a static frontend under `apps/frontend/site`.

Rules:

- each page should have one clear render owner
- `app.js` provides shared utilities/bootstrap without competing renderers
- page-specific tables should be rendered by page-specific scripts only
- frontend API calls should be cache-friendly and bounded
- Pool and SOLO statistics must remain clearly separated
- no page should read raw runtime files directly

Recommended ownership model:

```text
index.html      Pool/SOLO status, radar, calculator, general summaries
miner.html      Pool + SOLO wallet lookup and worker/block/payment views
blocks.html     block / lifecycle table
payments.html   recorded payment history
connect.html    Pool 39333 / Pure SOLO 39334 instructions
api.html        public API documentation
```

---

## Deployment Model

Target environment:

- Oracle Cloud VM
- ARM64 / aarch64
- Ubuntu
- systemd
- nginx
- single host first
- 1 vCPU / 6 GB RAM friendly

Expected public exposure:

```text
80/tcp    optional redirect / certificate flow
443/tcp   public website and API
39333/tcp Pool Stratum mining
39334/tcp Pure SOLO Stratum mining
```

Expected private-only exposure:

```text
daemon RPC
wallet RPC
API backend bind port, if reverse-proxied locally
runtime snapshots
submitblock controls
payout controls
```

---

## Operations

Common focused checks:

```bash
./ops/scripts/prelaunch-repo-check.sh
PYTHONPATH=apps/api:ops/scripts python3 -m unittest tests.test_api_endpoints
PYTHONPATH=ops/scripts python3 -m unittest tests.test_payout_accounting tests.test_solo_payout_helper
bash -n ops/scripts/*.sh
git diff --check
```

Frontend-only checks:

```bash
node --check apps/frontend/site/assets/app.js
find apps/frontend/site/assets -maxdepth 1 -name '*.js' -print -exec node --check {} \;
git diff --check
```

Routine health checks should use bounded snapshots and generated summaries, not
full runtime JSONL scans.

---

## Safety Rules

Never expose through the website or public API:

- daemon RPC
- wallet RPC
- submitblock enable/budget settings
- wallet send commands
- payout admin/configuration commands
- raw JSONL event logs
- raw runtime snapshots

Avoid broad runtime scans such as:

```bash
cat .runtime/live-stratum/*.jsonl
rg keyword .runtime/live-stratum/
pandas.read_json(...)
```

Use bounded reads or generated snapshots instead.

Production submitblock and wallet payouts are private operational paths. Safety
comes from bounded send ceilings, candidate validation, persistent payment/action
records, file locking, replay/idempotency guards, and private master enable/disable
switches. Routine production operation does not require public or per-payment
approval, but operators can disable submit or payout processing immediately when
investigating an abnormal condition.

---

## Key Runbooks

- Snapshot pipeline: [`docs/runbooks/snapshot-pipeline.md`](docs/runbooks/snapshot-pipeline.md)
- Stratum activity ingest: [`docs/runbooks/stratum-activity-ingest.md`](docs/runbooks/stratum-activity-ingest.md)
- Reward calculator and log maintenance: [`docs/runbooks/reward-calculator-and-log-maintenance.md`](docs/runbooks/reward-calculator-and-log-maintenance.md)
- Controlled live submitblock: [`docs/runbooks/controlled-live-submitblock.md`](docs/runbooks/controlled-live-submitblock.md)
- Manual payout review: [`docs/runbooks/manual-payout-review.md`](docs/runbooks/manual-payout-review.md)
- Prelaunch checklist: [`docs/runbooks/prelaunch-checklist.md`](docs/runbooks/prelaunch-checklist.md)

---

## Milestones

- [`2026-06-05 controlled submitblock success`](docs/benchmarks/2026-06-05-controlled-submitblock-success.md)
- [`2026-06-09 first auto wallet payout self-test`](docs/benchmarks/2026-06-09-first-auto-wallet-payout-self-test.md)
- [`2026-08-11 first Pure SOLO mainnet mining-to-payout cycle`](docs/benchmarks/2026-08-11-pure-solo-mainnet-cycle.md)

The pre-SOLO baseline is retained as Git tag:
`baseline/pre-pure-solo-20260811`.

---

## Development Guidance

This project favors small, reviewable patches.

Preferred flow:

```text
inspect -> patch -> test
```

Priorities:

1. correctness
2. working result
3. stability
4. simplicity
5. low resource usage
6. maintainability
7. UI polish
8. extensibility

Avoid broad refactors, new dependencies, large databases, build systems, and
future-facing abstractions unless they solve a current operational problem.
