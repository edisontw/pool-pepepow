# PEPEPOW Pool Agent Guide

This repository is maintained for the PEPEPOW community pool.

Use this file as the first-read instruction document for OpenClaw, Codex, or any local coding agent working inside this repository.

---

## 1. Project Goal

Maintain a lightweight, single-coin PEPEPOW community mining pool.

Primary goals:

1. Keep the pool working.
2. Preserve mining correctness.
3. Keep services stable and recoverable.
4. Make small, reviewable fixes.
5. Avoid heavy dependencies and broad rewrites.

This is not a multi-coin pool, exchange payout platform, account system, or large commercial backend.

---

## 2. Current Architecture

Logical layers:

1. PEPEPOW daemon layer
   - Runs `PEPEPOWd`.
   - Provides private local RPC only.
   - Supplies block templates and chain state.
   - Must not be exposed publicly.

2. Pool core / Stratum layer
   - Handles miner connections.
   - Handles `mining.subscribe`, `mining.authorize`, and `mining.submit`.
   - Records share events.
   - Maintains lightweight wallet/worker activity.
   - Prepares candidate blocks when block target is met.
   - Real submitblock must remain guarded by explicit flags.

3. Runtime snapshot layer
   - Writes summarized JSON snapshots.
   - Avoids expensive live request-time log parsing.
   - Keeps API/frontend reads lightweight.

4. Public API layer
   - Runs behind nginx, normally on `127.0.0.1:8080`.
   - Serves `/api/*` endpoints.
   - Reads snapshots and safe summaries.
   - Must not expose daemon RPC, wallet RPC, submit controls, or raw runtime logs.

5. Frontend layer
   - Static frontend under `apps/frontend/site/`.
   - Served directly by nginx on the current host.
   - No dedicated frontend systemd unit is required for the current deployment variant.

6. Ops/runtime layer
   - systemd services.
   - nginx and TLS.
   - guarded scripts under `ops/scripts/`.
   - runtime files under `.runtime/live-stratum/`.

---

## 3. Current Public / Private Surface

Public surface:

- HTTPS website: `https://pool.pepepow.net`
- Public API under `/api/*`
- Stratum mining port, currently expected around `39333`

Private/internal surface:

- daemon RPC
- wallet RPC
- `.runtime/live-stratum/launch.env`
- raw JSONL runtime logs
- candidate submit tooling
- payout tooling
- systemd environment files
- nginx config

Never expose internal surfaces through frontend, API, nginx, or public scripts.

---

## 4. Default Agent Workflow

For normal bug fixes or small improvements:

```text
inspect -> patch -> focused test -> report
```

Rules:

- Inspect only 1-3 relevant source files first.
- Patch the smallest working area.
- Prefer fixes over diagnostics.
- Run focused tests only.
- Do not run broad repository audits unless explicitly requested.
- Do not restart services unless explicitly requested.
- Do not change daemon, wallet, nginx, systemd, submitblock, or payout behavior unless explicitly requested.
- If the same test fails twice without a new hypothesis, stop and report the next minimal step.

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
tail -n 200 .runtime/live-stratum/specific-file.jsonl
tail -n 2000 .runtime/live-stratum/specific-file.jsonl
rg "keyword" .runtime/live-stratum/specific-file.jsonl | tail -n 50
```

API and frontend paths must not parse raw JSONL on request paths.

---

## 6. Safe Read-Only Commands

These are generally safe for local status checks:

```bash
git status --short
bash -n ops/scripts/*.sh
curl -s http://127.0.0.1:8080/api/health | jq
curl -s http://127.0.0.1:8080/api/pool/summary | jq
./ops/scripts/live-stratum.sh status
./ops/scripts/live-stratum.sh drill-status
./ops/scripts/agent-safe-status.sh
```

Bounded candidate checks:

```bash
./ops/scripts/live-stratum.sh candidate-outcomes 40
./ops/scripts/live-stratum.sh candidate-events 20
./ops/scripts/live-stratum.sh accepted-candidates
```

Bounded payout observation only:

```bash
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
curl -s http://127.0.0.1:8080/api/payments | jq
```

---

## 7. Commands Requiring Explicit Operator Approval

Do not run these unless the operator explicitly asks for them in the current task:

```bash
./ops/scripts/live-stratum.sh systemd-restart
sudo systemctl restart pepepow-pool-stratum.service
sudo systemctl restart pepepow-pool-api.service
sudo systemctl restart pepepow-pool-core.service
sudo systemctl reload nginx
```

Real submitblock requires explicit approval:

```bash
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true \
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1 \
./ops/scripts/live-stratum.sh systemd-restart
```

Real wallet payout requires explicit approval:

```bash
PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true \
PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=1 \
./ops/scripts/live-stratum.sh payout-wallet-send-once ...
```

---

## 8. Never Do By Default

Never do these by default:

- Enable real submitblock.
- Enable wallet payout.
- Open daemon RPC publicly.
- Open wallet RPC publicly.
- Delete runtime data.
- Reset chain data.
- Rewrite large architecture areas.
- Add Redis, database, account system, or multi-coin abstraction without a direct request.
- Add public admin payout or submit controls.
- Perform unlimited log scans.

---

## 9. Focused Test Commands

Common focused checks:

```bash
python3 -m unittest tests.test_stratum_ingress
PYTHONPATH=apps/api python3 -m unittest tests.test_api_endpoints
PYTHONPATH=ops/scripts python3 -m unittest tests.test_payout_accounting
bash -n ops/scripts/*.sh
git diff --check
```

Use the smallest relevant test for the touched files.

---

## 10. Report Format

Always report in this format:

```text
Done:
Changed:
Test:
Result:
Next:
```

For completed standalone patches, also include:

```text
Commit title:
Commit body:
```

Keep reports short. Do not paste large logs.
