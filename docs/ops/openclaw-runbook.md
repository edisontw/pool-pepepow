# OpenClaw Operations Runbook

This document summarizes how OpenClaw should monitor and manage the PEPEPOW community pool from a local repository checkout.

It is intentionally read-heavy and conservative. Runtime changes must be explicit.

---

## 1. Monitoring and Management Architecture

OpenClaw should treat the pool as a single-host, service-oriented stack:

```text
Miner
  -> public Stratum port
  -> pepepow-pool-stratum.service
  -> runtime snapshots / share events
  -> pepepow-pool-api.service
  -> nginx / HTTPS frontend
  -> users
```

Supporting internal path:

```text
PEPEPOWd private RPC
  -> pool-core snapshot producer
  -> pool-snapshot.json
  -> API summary endpoints
```

Candidate / payout paths are guarded operational paths, not normal public management paths:

```text
candidate event
  -> candidate artifact / outcome snapshot
  -> accepted-candidates API surface
```

```text
confirmed eligible block
  -> payout-candidates
  -> payout-review
  -> guarded wallet-send only when explicitly authorized
```

OpenClaw should normally observe these paths through existing scripts and API endpoints rather than reading raw logs or calling RPC directly.

---

## 2. Service Map

Expected current services:

| Component | Service / Owner | Notes |
|---|---|---|
| Daemon | `PEPEPOWd` / daemon service | Private RPC only |
| Pool core snapshot | `pepepow-pool-core.service` | Owns chain/runtime snapshot path |
| Stratum ingress | `pepepow-pool-stratum.service` | Owns miner ingest and activity snapshot |
| API | `pepepow-pool-api.service` | Local backend, normally `127.0.0.1:8080` |
| Web/TLS | `nginx` | Serves static frontend and proxies `/api/*` |
| Frontend | static files | Current host serves `apps/frontend/site/` directly through nginx |

Current deployment note:

- `pepepow-pool-frontend.service` may be absent.
- This is expected when nginx serves the static frontend directly.
- Do not treat a missing frontend service as a pool failure on this host.

---

## 3. Public vs Internal Boundary

Public:

- `https://pool.pepepow.net`
- `/api/*` safe read-only API
- Stratum mining port

Internal only:

- daemon RPC
- wallet RPC
- `.runtime/live-stratum/launch.env`
- candidate submit controls
- payout controls
- raw JSONL event logs
- nginx/systemd configs

OpenClaw must not create public endpoints for internal controls.

---

## 4. Human Monitoring Commands

Use these for routine manual monitoring.

### 4.1 Overall safe status

```bash
./ops/scripts/agent-safe-status.sh
```

### 4.2 Git state

```bash
git status --short
git diff --check
```

### 4.3 Service state

```bash
systemctl status pepepow-pool-stratum.service --no-pager
systemctl status pepepow-pool-api.service --no-pager
systemctl status pepepow-pool-core.service --no-pager
systemctl status nginx --no-pager
```

### 4.4 API checks

```bash
curl -s http://127.0.0.1:8080/api/health | jq
curl -s http://127.0.0.1:8080/api/pool/summary | jq
curl -s http://127.0.0.1:8080/api/network/summary | jq
curl -s http://127.0.0.1:8080/api/blocks | jq
curl -s http://127.0.0.1:8080/api/payments | jq
```

### 4.5 Public web checks

```bash
curl -I https://pool.pepepow.net
curl -s https://pool.pepepow.net/api/health | jq
```

### 4.6 Stratum / submit safety status

```bash
./ops/scripts/live-stratum.sh status
./ops/scripts/live-stratum.sh drill-status
```

Expected safe default for public/community operation unless explicitly in a self-test window:

```text
real_submit_enabled: False
```

During private sustained self-test, the operator may intentionally enable sustained submit. Do not change this state without explicit instructions.

### 4.7 Candidate observation

```bash
./ops/scripts/live-stratum.sh candidate-events 20
./ops/scripts/live-stratum.sh candidate-outcomes 40
./ops/scripts/live-stratum.sh accepted-candidates
curl -s http://127.0.0.1:8080/api/accepted-candidates | jq
```

### 4.8 Payout observation

Read-only / candidate generation:

```bash
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
curl -s http://127.0.0.1:8080/api/payments | jq
```

Wallet send is not a routine monitoring command.

---

## 5. Runtime File Rules

Runtime directory:

```text
.runtime/live-stratum/
```

Safe to list:

```bash
ls -lh .runtime/live-stratum/*.json .runtime/live-stratum/*.jsonl 2>/dev/null | tail -n 30
```

Safe bounded reads:

```bash
tail -n 200 .runtime/live-stratum/specific-file.jsonl
tail -n 2000 .runtime/live-stratum/specific-file.jsonl
rg "keyword" .runtime/live-stratum/specific-file.jsonl | tail -n 50
```

Do not run:

```bash
cat .runtime/live-stratum/*.jsonl
rg keyword .runtime/live-stratum/
pandas.read_json(...)
```

---

## 6. Change Management Rules

OpenClaw should only make changes when the user asks for a patch.

Default allowed change types:

- small bug fix
- focused frontend wording/style fix
- API fallback/read fix
- ops script syntax/safety fix
- documentation update
- focused test update

Avoid:

- broad refactor
- multi-coin abstraction
- new heavy dependency
- new database/Redis requirement
- new public admin endpoint
- wallet automation changes
- submitblock behavior changes

---

## 7. Commands Requiring Explicit Approval

Restart/reload:

```bash
./ops/scripts/live-stratum.sh systemd-restart
sudo systemctl restart pepepow-pool-stratum.service
sudo systemctl restart pepepow-pool-api.service
sudo systemctl restart pepepow-pool-core.service
sudo systemctl reload nginx
```

Real submitblock:

```bash
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true \
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1 \
./ops/scripts/live-stratum.sh systemd-restart
```

Wallet payout:

```bash
PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true \
PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=1 \
./ops/scripts/live-stratum.sh payout-wallet-send-once ...
```

Data deletion or chain/wallet operations always require explicit approval.

---

## 8. Focused Test Matrix

Use the smallest relevant tests.

Stratum / mining ingress:

```bash
python3 -m unittest tests.test_stratum_ingress
```

API:

```bash
PYTHONPATH=apps/api python3 -m unittest tests.test_api_endpoints
```

Payout/accounting helper:

```bash
PYTHONPATH=ops/scripts python3 -m unittest tests.test_payout_accounting
```

Shell scripts:

```bash
bash -n ops/scripts/*.sh
```

Diff hygiene:

```bash
git diff --check
```

---

## 9. Normal Report Format

OpenClaw should report:

```text
Done:
Changed:
Test:
Result:
Next:
```

For a standalone completed patch, add:

```text
Commit title:
Commit body:
```

Keep output short. Do not paste large logs.
