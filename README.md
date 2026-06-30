# pool-pepepow

PEPEPOW-only community mining pool for a single operator-managed Ubuntu host.

This repository is focused on a lightweight, maintainable PEPEPOW pool stack for
community testing, learning, and controlled public mining. It is intentionally
single-coin, snapshot/API-driven, and suitable for a small ARM64 Oracle Cloud
instance.

The current stack includes:

- public static website
- read-only public API
- active Stratum ingress
- daemon-template-backed mining jobs
- share/activity snapshots
- candidate follow-up observation
- guarded submitblock validation
- round and payout review tooling
- public manual payment history
- private operator-owned guarded wallet payout tooling

Automatic wallet payout tooling exists only as an operator-controlled private
path. It is not a public payout control surface and must not be exposed through
the website or API.

---

## Status

Current target: **single-coin PEPEPOW community pool MVP**

Operational goals:

- miners can connect and submit shares
- frontend shows pool, network, blocks, payments, and miner lookup data
- public API reads snapshots only
- Stratum, daemon RPC, wallet RPC, submit controls, and payout controls remain
  separated
- payout records are public only after they are recorded as completed actions
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
    Must consume public API endpoints only.

  pool-core/
    Stratum ingress, template-backed mining jobs, share accounting,
    activity snapshots, candidate events, and guarded submitblock path.

ops/
  scripts/
    Deployment and operator helpers.
    Includes payout review, carry, preflight, guarded one-shot send,
    and private wallet payout commands.

  systemd/
    Example systemd units.

  nginx/
    Example nginx HTTPS and API reverse-proxy configuration.

docs/
  Deployment docs, architecture notes, runbooks, benchmarks, and
  operational records.

tests/
  Focused Python tests for API, payout accounting, Stratum ingress,
  and related operational logic.
```

---

## Public Surface

Public components:

- HTTPS website
- read-only HTTPS API
- Stratum mining endpoint
- block view
- miner lookup
- manual payment history
- MiningPoolStats-compatible `/api/stats`
- secondary `/api/status`

Private/operator-only components:

- daemon RPC
- wallet RPC
- submitblock controls
- payout candidate review commands
- wallet send commands
- admin controls
- raw runtime snapshots
- raw event logs

The frontend must never call daemon RPC, wallet RPC, submit tooling, payout
commands, raw JSONL files, or internal runtime files.

---

## Current Public API

Common endpoints:

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

API rules:

- public endpoints are read-only
- request paths should read snapshots or summaries
- no public endpoint should parse large raw runtime logs
- no endpoint should expose daemon RPC, wallet RPC, submit controls, or payout
  controls
- malformed or missing snapshots should degrade safely

---

## Frontend Rules

The website is a static frontend under `apps/frontend/site`.

Rules:

- each page should have one clear render owner
- `app.js` should act as shared utilities/bootstrap, not as a competing renderer
  for every table
- page-specific tables should be rendered by page-specific scripts only
- static asset query strings should be updated consistently after frontend
  changes
- frontend API calls should be cache-friendly and bounded
- no page should read raw runtime files directly

Recommended ownership model:

```text
index.html      homepage status, radar, calculator, general pool summary
miner.html      wallet lookup, worker table, reward analysis
blocks.html     block / lifecycle table
payments.html   recorded payment history
connect.html    mining instructions
api.html        public API documentation
```

When updating the frontend, check for duplicate render targets such as:

```text
#payments-table
#blocks-table
miner lookup containers
reward analysis containers
homepage status/radar/calculator containers
```

Duplicate render ownership can cause a page to briefly show the new layout and
then revert to an older table after another script runs.

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
39333/tcp Stratum mining endpoint, if configured
```

Expected private-only exposure:

```text
daemon RPC
wallet RPC
API backend bind port, if reverse-proxied locally
runtime snapshots
submitblock controls
payout commands
```

---

## Operations

Common focused checks:

```bash
./ops/scripts/prelaunch-repo-check.sh
PYTHONPATH=apps/api:ops/scripts python3 -m unittest tests.test_api_endpoints
PYTHONPATH=ops/scripts python3 -m unittest tests.test_payout_accounting
bash -n ops/scripts/*.sh
git diff --check
```

Frontend-only checks:

```bash
node --check apps/frontend/site/assets/app.js
find apps/frontend/site/assets -maxdepth 1 -name '*.js' -print -exec node --check {} \;
git diff --check
```

Broader local validation:

```bash
python3 -m unittest discover tests
```

Routine payout health checks should use bounded snapshot commands and should not
scan full runtime JSONL files.

---

## Safety Rules

Do not expose or automate these through the public website or public API:

- daemon RPC
- wallet RPC
- submitblock enable flags
- wallet send commands
- payout admin commands
- raw JSONL event logs
- raw runtime snapshots

Do not run broad runtime scans such as:

```bash
cat .runtime/live-stratum/*.jsonl
rg keyword .runtime/live-stratum/
pandas.read_json(...)
```

Use bounded reads or generated snapshots instead.

Real submitblock and wallet payout actions must remain explicit operator actions
with guards such as enable flags and max-send limits.

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
