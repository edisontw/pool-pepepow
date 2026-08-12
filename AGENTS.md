# PEPEPOW Pool Agent Guide

This repository is maintained for the production PEPEPOW community Pool + Pure SOLO stack.

Use this file as the first-read instruction document for OpenClaw, Codex, or any local coding agent working inside this repository.

---

## 1. Project Goal and Priority

Maintain a lightweight, single-coin PEPEPOW community mining pool.

Priority order:

1. Correctness
2. Working result
3. Stability
4. Simplicity
5. Low resource use
6. Maintainability
7. UI
8. Extensibility

Do not delay a clear production fix for a larger redesign.

This is not a multi-coin pool, exchange payout platform, account system, or large commercial backend.

---

## 2. Production Baseline

The current stack is production, not a dry-run-only milestone.

Active baseline includes:

- Pool Stratum on `39333`
- Pure SOLO Stratum on `39334`
- daemon-template jobs
- share validation
- pool-share / block-candidate classification
- production guarded `submitblock`
- candidate lifecycle tracking
- Pool round/accounting
- Pure SOLO finder accounting
- guarded automated payouts
- payment history/snapshots
- restart recovery
- read-only API/frontend

Pure SOLO is isolated from Pool accounting. SOLO shares must never affect Pool round weights or boundaries.

The application-level default for real submit may remain conservative, but the production Pure SOLO service must load its persistent environment from:

```text
/home/ubuntu/pool-pepepow/ops/env/pool-stratum-solo.env
```

For production port `39334`, that environment must keep:

```text
PEPEPOW_POOL_CORE_MINING_MODE=solo
PEPEPOW_POOL_CORE_STRATUM_BIND_PORT=39334
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=<positive bounded value>
```

`pepepow-pool-stratum-solo.service` runs `check-solo-production-env.sh` before startup so the public SOLO listener does not silently run in no-submit/dry-run mode.

---

## 3. Architecture and Security Boundaries

Logical layers:

1. PEPEPOW daemon layer
   - Runs `PEPEPOWd`.
   - Provides private local RPC only.
   - Supplies block templates, chain state, and production submitblock.
   - Must not be exposed publicly.

2. Pool core / Stratum layer
   - Handles `mining.subscribe`, `mining.authorize`, and `mining.submit`.
   - Records share events.
   - Validates shares and prepares/submits qualifying candidates.
   - Pool and SOLO use separate runtime/accounting domains.

3. Runtime snapshot layer
   - Writes summarized JSON snapshots.
   - Avoids expensive live request-time log parsing.

4. Public API layer
   - Runs behind nginx, normally on `127.0.0.1:8080`.
   - Reads snapshots and safe summaries.
   - Must not expose daemon RPC, wallet RPC, submit controls, payout controls, or raw runtime logs.

5. Frontend layer
   - Static frontend under `apps/frontend/site/`.
   - Reads API/cache/snapshots only.

6. Ops/runtime layer
   - systemd, nginx/TLS, candidate lifecycle, accounting, payout, and health tooling.

Public surface:

- `https://pool.pepepow.net`
- read-only `/api/*`
- Pool Stratum `39333`
- Pure SOLO Stratum `39334`

Private/internal surface:

- daemon RPC
- wallet RPC
- raw JSONL/runtime files
- submit/payout tooling and controls
- systemd environment files
- nginx configuration

Never expose internal surfaces through frontend, API, or public passthroughs.

---

## 4. Default Agent Workflow

For normal maintenance and bug fixes:

```text
inspect -> patch -> focused test -> deploy/restart if needed -> smoke test
```

Rules:

- Inspect 1-3 relevant source files first; expand only when necessary.
- Prefer the smallest working patch.
- Root cause clear -> patch it.
- Test failure clear -> fix the failing path.
- After two diagnostic-only rounds, make a corrective patch or one high-information probe.
- Use at most three auto-fix loops for one patch.
- If the same test fails twice without a new hypothesis, change approach or stop.
- Do not perform broad repository audits unless requested.
- Normal code deployment may restart/reload the affected Pool, SOLO, API, payout, nginx, or daemon service when required.
- Do not restart unrelated healthy services.

Production `submitblock` and guarded auto payout are normal operating functions. Do not turn them off merely because an old benchmark/runbook describes an earlier dry-run milestone.

---

## 5. Runtime Log Guardrails

Never run unbounded runtime log reads.

Forbidden:

```bash
cat .runtime/live-stratum/*.jsonl
pandas.read_json(...)
rg keyword .runtime/live-stratum/
```

Allowed bounded forms:

```bash
tail -n 200 specific-file.jsonl
tail -n 2000 specific-file.jsonl
rg "keyword" specific-file.jsonl | tail -n 50
```

Prefer snapshots, summaries, bounded tails, and bounded grep. API/frontend request paths must not parse large raw JSONL files.

---

## 6. Routine Production Operations

These are normal maintenance when relevant to the task:

- modify Pool/SOLO core, API, frontend, ops, payout, or accounting code
- query daemon/wallet read-only state
- refresh candidate, round, payout, and payment snapshots
- run existing guarded auto payout
- allow normal validated production `submitblock`
- deploy and restart/reload the affected service after focused tests
- repair systemd/deployment configuration
- run bounded production diagnostics

Normal flow:

```text
candidate -> validation -> submitblock -> lifecycle
confirmed/mature -> accounting -> guarded payout -> txid record
```

Useful checks:

```bash
git status --short
bash -n ops/scripts/*.sh
curl -s http://127.0.0.1:8080/api/health | jq
curl -s http://127.0.0.1:8080/api/pool/summary | jq
curl -s http://127.0.0.1:8080/api/solo/summary | jq
systemctl status pepepow-pool-stratum.service --no-pager
systemctl status pepepow-pool-stratum-solo.service --no-pager
```

---

## 7. Operations Requiring Explicit Operator Approval

Stop and obtain explicit operator approval for:

- manual/exceptional wallet transfer or sweep
- private key / seed operations
- changing payout destination or pool reward wallet
- changing Pool/SOLO fee or reward distribution
- operator backfill assigning rewards to a specified wallet
- unbounded/bulk payout or disabling `MAX_SENDS`
- disabling replay/orphan/maturity/coinbase safety guards
- manually submitting a non-normal candidate or bypassing candidate validation
- daemon reindex
- wallet rescan/recovery
- deleting chain, wallet, payment, candidate, round, or audit data
- exposing daemon RPC, wallet RPC, Redis, submit controls, or payout controls publicly
- large irreversible migration or production architecture rewrite

These approval requirements do not apply to normal production candidate submission or the existing guarded automatic payout path.

---

## 8. Submit and Payout Guards

Keep submitblock protections intact:

- block-target validation
- current/fresh previous-block checks
- bounded send ceiling
- daemon result recording
- candidate lifecycle evidence

Keep payout protections intact:

- confirmed/mature and orphan protection
- expected pool coinbase verification
- valid recipient and minimum payout
- duplicate/replay protection
- `MAX_SENDS`
- txid validation
- append-only payment record

Do not solve a payout or submit problem by bypassing these guards.

---

## 9. Focused Test Commands

Use the smallest relevant test set for touched files:

```bash
python3 -m unittest tests.test_stratum_ingress
PYTHONPATH=apps/api python3 -m unittest tests.test_api_endpoints
PYTHONPATH=ops/scripts python3 -m unittest tests.test_payout_accounting
PYTHONPATH=ops/scripts python3 -m unittest tests.test_track_rounds
bash -n ops/scripts/*.sh
git diff --check
```

Routine health checks with no code changes do not require the full unittest suite.

---

## 10. Historical Documentation Rule

Benchmark and design documents from earlier milestones may intentionally describe:

- real submit disabled
- payout paused/manual
- pre-production or dry-run behavior

Treat those as historical evidence, not current production configuration.

When current operational behavior conflicts with an old benchmark, use this guide, current service/env configuration, current architecture docs, and current production code as the source of truth.

---

## 11. Report Format

Use:

```text
Done:
Changed:
Test:
Result:
Next:
```

For a completed standalone patch, also include:

```text
Commit title:
Commit body:
```

Keep reports short and do not paste large logs.
