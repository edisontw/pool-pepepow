# Manual Payout Design：PEPEPOW Pool

Date: 2026-06-06
Status: Design draft
Scope: Manual payout only

---

## 1. Goal

This document defines the smallest safe manual payout design for the PEPEPOW community pool.

The goal is to support a traceable operator-reviewed payout flow without introducing wallet RPC automation, automatic payout workers, Redis, a database, or a public admin panel.

Target flow:

```text
confirmed pool block
-> round shares frozen
-> payout candidates generated
-> operator review
-> manual wallet transfer
-> txid recorded
-> public payment history updated
```

This design intentionally keeps payout execution manual. The pool software may prepare payout candidates and record completed manual payments, but it must not send funds automatically.

---

## 2. Scope

### In scope

- PEPEPOW only.
- Manual payout candidate generation.
- Manual operator review.
- Manual payment recording by txid.
- Payment history snapshot for API/frontend.
- Confirmed-block-only eligibility.
- Immature/orphan protection.
- Append-only payment action log.
- Lightweight JSON / JSONL storage.

### Out of scope

- Wallet RPC automatic transfer.
- Automatic payout worker.
- Auto-exchange payout.
- User accounts or login.
- Large admin panel.
- Redis or database requirement.
- Public payout control endpoints.
- Frontend-triggered payout actions.
- Balance carry implementation in the first version.

---

## 3. Design Principles

1. **Manual first**  
   The system produces payout candidates only. Operator manually sends funds from wallet tooling.

2. **Confirmed only**  
   Immature, orphaned, unknown, or unconfirmed candidates must not become payable.

3. **No wallet exposure**  
   No script in this phase should call wallet RPC, unlock wallet, or send transactions.

4. **Traceable actions**  
   Every recorded manual payment must be appended to an action log with txid.

5. **Snapshot for public API**  
   API reads a prebuilt payment snapshot, not raw accounting logs on request paths.

6. **Small-host friendly**  
   No heavy DB, no full runtime log scans, no pandas, no high-frequency RPC.

---

## 4. Eligibility Rules

A pool-found block is eligible for payout only when all conditions are true:

```text
lifecycleStatus == confirmed
confirmations >= PEPEPOW_PAYOUT_MIN_CONFIRMATIONS
orphan == false
reward > 0
round_closed == true
payout_status == unpaid
```

Blocked states:

```text
blocked_immature
blocked_orphan
blocked_unconfirmed
blocked_missing_round
blocked_zero_weight
blocked_missing_reward
blocked_already_paid
```

Suggested initial environment settings:

```bash
PEPEPOW_PAYOUT_MIN_CONFIRMATIONS=101
PEPEPOW_POOL_FEE_PERCENT=1.0
PEPEPOW_MIN_PAYOUT=100000
PEPEPOW_PAYOUT_DUST_THRESHOLD=1000
```

`PEPEPOW_PAYOUT_MIN_CONFIRMATIONS` should be configurable, not hard-coded.

---

## 5. Accounting Model

### 5.1 Initial model

Use one confirmed pool block as one payout unit.

A payout candidate references:

- candidate id
- block height
- block hash
- confirmed lifecycle status
- gross reward
- pool fee
- net reward
- round share total
- per-wallet weights
- per-wallet proposed payout amount

### 5.2 Round weight

Preferred weight:

```text
share_difficulty_sum
```

Fallback weight if difficulty sum is not available yet:

```text
accepted_share_count
```

The fallback must be explicitly marked in the payout candidate metadata:

```json
"weightMode": "accepted_share_count"
```

### 5.3 Calculation

```text
gross_reward = block_reward
pool_fee = gross_reward * pool_fee_percent / 100
net_reward = gross_reward - pool_fee
wallet_amount = net_reward * wallet_weight / total_round_weight
```

### 5.4 Threshold behavior

First version should avoid balance carry complexity.

Recommended first-version behavior:

```text
if wallet_amount < PEPEPOW_MIN_PAYOUT:
    status = below_threshold
    do not include in manual payment list
```

Do not expose pending balance until balance carry logic exists and is tested.

---

## 6. Runtime Files

Recommended runtime files:

```text
.runtime/live-stratum/rounds-snapshot.json
.runtime/live-stratum/payout-candidates.json
.runtime/live-stratum/payment-actions.jsonl
.runtime/live-stratum/payments-snapshot.json
```

### 6.1 `payout-candidates.json`

Written atomically by the payout candidate generator.

Example:

```json
{
  "generatedAt": "2026-06-06T12:00:00Z",
  "items": [
    {
      "candidateId": "height-4573284",
      "blockHash": "00000007bb3b63116d0fac877f97ea45ba47b2c9759aadf81b5e8d2a9b18daf1",
      "height": 4573284,
      "lifecycleStatus": "confirmed",
      "confirmations": 120,
      "status": "ready_for_manual_review",
      "grossReward": 123456789.0,
      "poolFeePercent": 1.0,
      "poolFeeAmount": 1234567.89,
      "netReward": 122222221.11,
      "weightMode": "share_difficulty_sum",
      "roundShareTotal": 5000.0,
      "payouts": [
        {
          "wallet": "Pxxxx",
          "weight": 2500.0,
          "amount": 61111110.55,
          "status": "pending_manual_payment"
        }
      ],
      "blockedReason": null
    }
  ]
}
```

### 6.2 `payment-actions.jsonl`

Append-only manual payment action log.

Example row:

```json
{"timestamp":"2026-06-06T12:30:00Z","action":"manual_payment_recorded","candidateId":"height-4573284","wallet":"Pxxxx","amount":61111110.55,"txid":"abcdef...","operator":"manual","note":"paid from wallet manually"}
```

### 6.3 `payments-snapshot.json`

Generated from candidate data plus recorded payment actions.

Example:

```json
{
  "generatedAt": "2026-06-06T12:31:00Z",
  "items": [
    {
      "timestamp": "2026-06-06T12:30:00Z",
      "wallet": "Pxxxx",
      "amount": 61111110.55,
      "txid": "abcdef...",
      "candidateId": "height-4573284",
      "blockHeight": 4573284,
      "blockHash": "00000007bb3b63116d0fac877f97ea45ba47b2c9759aadf81b5e8d2a9b18daf1",
      "status": "paid_manual"
    }
  ]
}
```

---

## 7. Operator Workflow

### Step A: Generate payout candidates

```bash
./ops/scripts/live-stratum.sh payout-candidates
```

Expected behavior:

- Read accepted confirmed pool candidates.
- Read round/share snapshot.
- Generate `.runtime/live-stratum/payout-candidates.json` atomically.
- Never call wallet RPC.
- Never send funds.
- Missing inputs produce blocked statuses, not crashes.

### Step B: Review payout candidates

```bash
./ops/scripts/live-stratum.sh payout-review
```

Expected output should include:

```text
Block height
Block hash
Lifecycle status
Confirmations
Gross reward
Pool fee
Net reward
Wallet count
Total payout amount
Below-threshold count
Blocked candidates
```

### Step C: Manual wallet transfer

Operator manually sends funds using external wallet tooling.

This is outside pool automation.

### Step D: Record completed payment

```bash
./ops/scripts/live-stratum.sh record-payment \
  --candidate-id height-4573284 \
  --wallet Pxxxx \
  --amount 61111110.55 \
  --txid abcdef...
```

Validation rules:

- Candidate must exist.
- Candidate must be ready for manual review.
- Wallet must exist in candidate payout list.
- Amount must match expected payout amount within a strict tolerance.
- Txid must be non-empty.
- Same `candidateId + wallet` must not be recorded twice.
- Script must append to `payment-actions.jsonl`.
- Script must regenerate `payments-snapshot.json` atomically.
- Script must not call wallet RPC.

---

## 8. API Design

### 8.1 `/api/payments`

Current placeholder endpoint can be upgraded to read:

```text
.runtime/live-stratum/payments-snapshot.json
```

Fallback behavior:

```json
{"items":[]}
```

Fallback must apply when the snapshot is:

- missing
- malformed
- unreadable
- missing `items`

The API must not parse `payment-actions.jsonl` on request paths.

Example response:

```json
{
  "items": [
    {
      "timestamp": "2026-06-06T12:30:00Z",
      "wallet": "Pxxxx",
      "amount": 61111110.55,
      "txid": "abcdef...",
      "blockHeight": 4573284,
      "blockHash": "00000007bb3b63116d0fac877f97ea45ba47b2c9759aadf81b5e8d2a9b18daf1",
      "status": "paid_manual"
    }
  ]
}
```

### 8.2 `/api/miner/<wallet>`

First version may expose only recorded manual payments:

```text
recentPayments
totalPaidManual
```

Do not expose:

```text
pendingBalance
payableBalance
estimatedEarnings
```

until balance carry and payout accounting are implemented and tested.

---

## 9. Frontend Design

### 9.1 Payments page wording

Recommended text:

```text
Manual payments

Payments are processed manually after a pool-found block is confirmed and reviewed.
Immature or orphaned blocks are not payable.
Only recorded completed payments are shown here.
```

### 9.2 Miner page wording

Recommended label:

```text
Manual payments recorded
```

Avoid these words unless the accounting model actually supports them:

```text
earned
balance
payable
guaranteed
pending reward
```

Allowed after manual txid is recorded:

```text
paid_manual
recorded payment
manual payment history
```

---

## 10. Script Commands

Add commands to `ops/scripts/live-stratum.sh`:

```text
payout-candidates
payout-review
record-payment
```

Suggested implementation structure:

```text
ops/scripts/build_payout_candidates.py
ops/scripts/record_manual_payment.py
```

Do not put large accounting logic directly into the shell script.

---

## 11. Safety Checks

Required safety behavior:

- No wallet RPC calls.
- No automatic transaction send.
- No public admin endpoint.
- No raw JSONL parsing from API request path.
- No payout from immature blocks.
- No payout from orphan blocks.
- No duplicate wallet payment for same candidate.
- Atomic snapshot writes.
- Append-only payment action log.

---

## 12. Tests

Minimum focused tests:

```text
test_confirmed_candidate_generates_payout_candidate
test_immature_candidate_is_blocked
test_orphan_candidate_is_blocked
test_missing_round_is_blocked
test_zero_weight_is_blocked
test_record_payment_requires_existing_candidate_wallet
test_record_payment_rejects_duplicate_wallet_candidate
test_payments_api_returns_empty_items_for_missing_snapshot
test_payments_api_reads_snapshot_items
```

Suggested commands:

```bash
PYTHONPATH=apps/api:ops/scripts python3 -m unittest tests.test_api_endpoints
PYTHONPATH=ops/scripts python3 -m unittest tests.test_manual_payout
bash -n ops/scripts/*.sh
```

---

## 13. Implementation Prompt for Agent

```markdown
Run in bounded auto-fix mode.

Goal:
Implement the smallest manual payout surface for PEPEPOW pool.

Scope:
- Manual payout only.
- No wallet RPC.
- No automatic send.
- No payout worker.
- No Redis or DB.
- Do not expose admin payout tooling publicly.
- Do not change daemon RPC, submitblock flags, Stratum behavior, or nginx.

Implement:
1. Add a payout candidate generator script:
   - Reads accepted confirmed pool candidates and round/share snapshot data.
   - Only confirmed blocks are eligible.
   - Immature or orphan blocks must be blocked.
   - Missing round/share data must produce blocked status, not crash.
   - Writes `.runtime/live-stratum/payout-candidates.json` atomically.

2. Add manual payment recording:
   - Append payment action rows to `.runtime/live-stratum/payment-actions.jsonl`.
   - Generate `.runtime/live-stratum/payments-snapshot.json`.
   - Require candidate id, wallet, amount, txid.
   - Reject duplicate wallet payment for the same candidate.
   - Do not call wallet RPC.

3. Add `live-stratum.sh` commands:
   - `payout-candidates`
   - `payout-review`
   - `record-payment`

4. Update API `/api/payments`:
   - Read `payments-snapshot.json`.
   - Missing or malformed snapshot returns `{"items":[]}`.
   - Do not parse raw JSONL on request path.

5. Update frontend payments page:
   - Show manual payment history.
   - Clearly state payout is manual.
   - Do not show balance/payable/earned wording unless already paid and recorded.

Files limit:
- Inspect 1–3 source files first.
- Prefer:
  - `ops/scripts/live-stratum.sh`
  - `apps/api/app.py` or API store file
  - frontend payments JS/HTML file
- Add only small helper script if needed.

Tests:
- Add focused unittest for payout candidate blocking and payment recording.
- Run:
  - `PYTHONPATH=apps/api:ops/scripts python3 -m unittest tests.test_api_endpoints`
  - focused payout test
  - `bash -n ops/scripts/*.sh`

Rules:
- No full runtime JSONL scan.
- No pandas.
- Use bounded reads only.
- Do not enable real submitblock.
- Do not touch wallet.
- No broad refactor.

Report:
Done:
Changed:
Test:
Result:
Next:
```

---

## 14. Suggested Commit After Implementation

Commit title:

```text
Add manual payout design and snapshot flow
```

Commit body:

```text
Add the first manual payout surface for PEPEPOW pool.

Implement payout candidate generation from confirmed pool candidates and round/share snapshots, manual payment recording by txid, and a payment snapshot consumed by the public payments API.

Keep payout execution manual and avoid wallet RPC, automatic send logic, Redis, DB, or public admin controls.
```

---

## 15. Current Recommended Next Step

Implement only:

```text
payout candidate generator
manual payment recorder
/api/payments snapshot fallback
payments page wording update
```

Do not implement balance carry or automatic payout in the first patch.
