# PEPEPOW Pool Architecture

This document is a deployer and agent reference for the current PEPEPOW-only
community Pool + Pure SOLO stack.

The deployment targets one low-resource Ubuntu ARM64/aarch64 host. Public
surfaces are the website, read-only API, Pool Stratum on `39333`, and Pure SOLO
Stratum on `39334`. Daemon RPC, wallet RPC, runtime files, submit controls, and
payout controls remain private/operator-only.

The current stack has active Pool and Pure SOLO Stratum ingress,
daemon-template-backed jobs, share validation, candidate follow-up, production
guarded submitblock, Pool accounting, Pure SOLO finder accounting, scheduled
private wallet payouts, replay protection, and public snapshot-driven Pool/SOLO
views.

## ASCII Diagram

```text
                             public internet
                                   |
                    +--------------+--------------+
                    |                             |
             +------v------+                Stratum TCP
             |    nginx    |                 39333 / 39334
             +------+------+                    |
                    |                 +----------+----------+
          +---------+---------+       |                     |
          |                   |   Pool Stratum          SOLO Stratum
   static frontend       read-only API   |                     |
          |                   |          +----------+----------+
          |             snapshot reads              |
          |                   |              daemon-template jobs
          |          +--------+--------+             |
          |          |                 |          PEPEPOWd
          |     Pool snapshots      SOLO snapshots    |
          |          |                 |              |
          |          +--------+--------+------ private RPC
          |                   |
          |             payout scheduler
          |              /           \
          |        Pool payout     SOLO payout
          |              \           /
          |               wallet RPC
          |
          +------ browser reads API only
```

## Component Table

| Component | Path / service | Purpose | Boundary |
|---|---|---|---|
| `PEPEPOWd` | external daemon | Chain state, templates, submitblock, wallet backend | RPC stays private |
| pool-core producer | `apps/pool-core/producer.py`, `pepepow-pool-core.service` | Writes network/Pool snapshots | Private process |
| Pool Stratum | `apps/pool-core/stratum_ingress.py`, `pepepow-pool-stratum.service` | Pool miner ingress on `39333`, shares, Pool candidates | Public TCP; private runtime |
| Pure SOLO Stratum | same ingress code, `pepepow-pool-stratum-solo.service` | SOLO miner ingress on `39334`, isolated shares/candidates | Public TCP; private SOLO runtime |
| API | `apps/api`, `pepepow-pool-api.service` | Read-only Pool/SOLO JSON from snapshots | Public through nginx |
| frontend | `apps/frontend/site` | Public static website | API-only reads |
| payout scheduler | existing payout systemd service/timer + `ops/scripts/live-stratum.sh` | Scheduled Pool + SOLO payout refresh/send workflow | Private operator service |
| ops scripts | `ops/scripts` | Candidate lifecycle, accounting, payout/replay tooling | Operator-only shell access |
| nginx | `ops/nginx` examples | HTTPS, static frontend, API proxy | Public web boundary |

## Mining Modes

### Pool Mining — port `39333`

Pool shares enter the shared Pool round/accounting path and are paid through the
existing Pool payout workflow.

### Pure SOLO — port `39334`

SOLO shares and candidates are written to an isolated SOLO runtime. A block
finder is the authenticated Stratum wallet/worker. A confirmed SOLO block pays
exactly one finder the pool-controlled miner reward after the configured SOLO
fee. Pool shares do not participate in SOLO reward weighting.

`miningMode` is server-defined as `pool` or `solo`; legacy events without the
field are treated as Pool data.

## Data Flow

```text
Pool miner -> 39333 -> Pool share/activity snapshot -> Pool accounting
SOLO miner -> 39334 -> SOLO share/activity snapshot -> SOLO finder accounting

candidate -> submit outcome -> candidate follow-up -> accepted-candidates
confirmed candidate -> payout candidate -> scheduled wallet send -> payment snapshot
API -> frontend
```

Key rules:

- Pool and SOLO runtime data stay separated.
- SOLO shares never add Pool share score.
- SOLO candidates never create Pool round boundaries.
- Pool payout generation ignores SOLO candidates.
- SOLO payout uses the confirmed coinbase output belonging to the configured
  pool reward address as the authoritative `minerRewardAmount`; reward amounts
  are not hard-coded.
- Frontend and API never read raw JSONL on the public request path.

## Public / Private Boundary

| Surface | Public? | Notes |
|---|---:|---|
| Website | Yes | Static frontend via nginx |
| API | Yes | Read-only `/api/*` JSON |
| Pool Stratum `39333` | Yes | Shared Pool mining |
| Pure SOLO Stratum `39334` | Yes | Finder-only SOLO mining |
| daemon RPC | No | Local/private only |
| wallet RPC | No | Private scheduled/operator tooling only |
| raw JSONL logs | No | Runtime internals |
| runtime snapshots | No direct access | API summarizes selected snapshots |
| submit controls | No | Private env/config only |
| payout controls | No | Private env/config only |
| Redis | No | Not required |

## Runtime File Ownership

Pool runtime examples:

| File | Written/read by | Public? |
|---|---|---:|
| `pool-snapshot.json` | pool-core producer / API | No direct access |
| `activity-snapshot.json` | Pool Stratum / API | No direct access |
| `share-events.jsonl` | Pool Stratum / bounded ops tooling | No |
| `accepted-candidates.json` | candidate tracker / API / payout | Summarized via API |
| `rounds-snapshot.json` | round tracker / API / payout | Summarized via API |
| `payout-candidates.json` | payout helper | No |
| `payments-snapshot.json` | payout helper / API | Summarized via API |

Pure SOLO runtime lives under the isolated `solo/` runtime path and includes:

```text
activity-snapshot.json
share-events.jsonl
candidate-events.jsonl
candidate-followup-events.jsonl
candidate-outcome-events.jsonl
accepted-candidates.json
solo-payout-candidates.json
solo-payment-actions.jsonl
solo-payments-snapshot.json
```

The API reads the safe SOLO snapshots only.

## systemd Service Ownership

| Service | Purpose |
|---|---|
| `pepepow-pool-core.service` | Pool/network snapshot producer |
| `pepepow-pool-stratum.service` | Pool Stratum `39333` |
| `pepepow-pool-stratum-solo.service` | Pure SOLO Stratum `39334` |
| `pepepow-pool-api.service` | Public read-only API |
| `pepepow-pool-auto-payout.service` + timer | Scheduled Pool/SOLO payout cycle |
| nginx / optional frontend service | Public website/API routing |

Pool and SOLO Stratum services can be restarted independently. A frontend/API
change should not restart mining services.

## Submit and Payout Safety

Production submitblock and wallet payout are intentionally private, automated
operational paths rather than public controls.

Safety is provided by:

- server-side candidate validation
- bounded production send ceilings
- private master enable/disable switches
- candidate-specific persistent action records
- replay/idempotency guards
- file locking around wallet sends
- wallet/address/amount validation
- Pool/SOLO accounting separation
- maturity/orphan checks before payout

The send ceilings are runaway-loop guards, not the primary duplicate-payment
mechanism. Already-paid candidate IDs remain blocked across later scheduled runs.

## API Read Rule

The API may read Pool/SOLO snapshots and safe sidecar summaries. It must not
expose daemon RPC, wallet RPC, submit controls, payout controls, or parse large
raw JSONL files per request.

Current public endpoints include:

```text
GET /api/health
GET /api/pool/summary
GET /api/network/summary
GET /api/blocks
GET /api/accepted-candidates
GET /api/rounds
GET /api/payments
GET /api/miner/<wallet>
GET /api/solo/summary
GET /api/solo/accepted-candidates
GET /api/solo/payments
GET /api/solo/miner/<wallet>
GET /api/stats
GET /api/status
```

## Agent Modification Guide

Use these ownership boundaries:

- Frontend: `apps/frontend/site`
- API: `apps/api`
- Stratum/mining: `apps/pool-core`
- Ops/payout: `ops/scripts`
- systemd/nginx: `ops/systemd`, `ops/nginx`
- Documentation: `docs`

Keep changes scoped. Do not alter daemon/wallet RPC, payout, nginx, or systemd
behavior for frontend/API/docs-only tasks.
