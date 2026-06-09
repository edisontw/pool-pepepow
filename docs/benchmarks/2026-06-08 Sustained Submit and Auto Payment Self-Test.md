# 2026-06-08 Sustained Submit and Auto Payment Self-Test

Date: 2026-06-08
Status: Active self-test mode
Scope: Private operator-owned mining and payout test

---

## 1. Summary

This document records the intentional transition from the earlier bounded controlled-submit drill model into a sustained real-submit and automatic wallet-payout self-test mode.

This mode is allowed only because the current mining wallet, pool reward wallet, and payout destination are controlled by the same operator. The purpose is to validate the complete pool loop under live mining conditions:

```text
miner shares
-> block candidate
-> submitblock
-> chain match
-> coinbase reward to pool wallet
-> payout candidate
-> wallet send
-> txid recorded
-> payments API/frontend visibility
```

This is not yet a public payout guarantee, not a general community payout policy, and not a statement that public automatic payouts are production-ready.

---

## 2. Historical Context

The earlier `2026-06-05-controlled-submitblock-success.md` milestone documented a bounded controlled submitblock drill with:

```text
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1
```

That milestone proved the submitblock pipeline could assemble a candidate block, submit it to the daemon, receive a success result, and later confirm the candidate hash on-chain.

At that time, the correct operational conclusion was conservative:

```text
real submit default-off
manual review before payout
no production payout readiness claim
```

This document records a later operator decision for a narrower private testing phase:

```text
sustained submit enabled
high submit budget allowed
automatic wallet payout allowed for eligible confirmed candidates
```

The earlier milestone remains historically accurate and should not be rewritten as if it had already approved sustained submit or automatic payout.

---

## 3. Current Self-Test Decision

For this private self-test phase, sustained real submit may remain enabled.

The intended runtime state is:

```bash
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1000000
PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true
```

The high submit budget is intentional for this self-test phase so that the pool can continue submitting block candidates during sustained mining without repeatedly reopening a short one-shot window.

Automatic wallet payout is also allowed for this self-test phase, but only for candidates that pass all payout eligibility checks.

---

## 4. Wallet Configuration

Expected pool reward wallet:

```text
PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
```

Expected miner payout wallet:

```text
PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD
```

Required Stratum / pool-core reward address configuration:

```bash
PEPEPOW_POOL_CORE_REWARD_ADDRESS=PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
```

Required sustained submit configuration:

```bash
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1000000
```

Required auto wallet payout configuration:

```bash
PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true
```

The active runtime environment must include the pool reward address. It is not enough for the value to exist only in `ops/env/pool-core.env.example`.

The expected active runtime file is usually:

```text
.runtime/live-stratum/launch.env
```

It should include at minimum:

```bash
PEPEPOW_POOL_CORE_REWARD_ADDRESS=PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1000000
PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true
```

---

## 5. Critical Safety Guards That Must Remain Enabled

Even in this bolder self-test mode, the following guards must remain active.

### 5.1 Coinbase reward mismatch guard

Old candidates produced before the pool reward wallet fix may have miner reward output sent to a nonstandard script such as:

```text
scriptPubKey: 51
```

Those candidates must remain blocked.

Required blocked status:

```text
blocked_coinbase_reward_mismatch
```

Condition:

```text
coinbaseMatchesExpectedPoolWallet == false
```

These candidates must never be marked:

```text
ready_for_manual_review
```

and must never reach wallet send preflight or automatic wallet send.

### 5.2 Already-paid guard

Candidates that have already produced a recorded payment must remain blocked.

Required blocked status:

```text
blocked_already_paid
```

This prevents duplicate payout for the same candidate and wallet.

### 5.3 Immature / orphan / unknown guard

The following candidate states must never be paid:

```text
immature
orphan
unknown
chain_match_not_found
candidate_recorded
submitted_without_chain_match
```

Only confirmed, coinbase-matched candidates may proceed.

### 5.4 Expected wallet guard

Automatic payout during this self-test should only send to the expected miner payout wallet:

```text
PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD
```

Any unexpected wallet should block or require manual review.

---

## 6. Eligibility Rules for Auto Payment in This Self-Test

A candidate may enter automatic wallet payout only when all conditions are true:

```text
lifecycleStatus == confirmed
coinbaseMatchesExpectedPoolWallet == true
expectedPoolRewardAddress == PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
blockedReason == null
status is ready / ready_for_manual_review / ready_for_wallet_send
wallet == PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD
not already paid
not immature
not orphan
not unknown
not coinbase mismatch
```

A candidate must not be paid when any of these are true:

```text
coinbaseMatchesExpectedPoolWallet == false
blockedReason == blocked_coinbase_reward_mismatch
blockedReason == blocked_already_paid
lifecycleStatus != confirmed
wallet is not expected self-test wallet
```

---

## 7. Acceptance Criteria

This self-test is successful only when all of the following are verified.

### 7.1 Submit path

```text
real_submit_enabled: True
real_submit_send_budget: 1000000
real_submit_error_count: 0
submit_status: submit-sent
```

At least one submitted candidate must later show:

```text
candidate_outcome_status: chain-match-found
followup_status: match-found
```

### 7.2 Coinbase path

For a new confirmed pool block after the reward-address fix, payout diagnostics must show:

```text
coinbaseMatchesExpectedPoolWallet: true
expectedPoolRewardAddress: PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
```

The PEPEPOW explorer should show the mining reward entering:

```text
PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
```

### 7.3 Payout candidate path

`payout-candidates` must classify only confirmed, coinbase-matched candidates as eligible.

Old script-51 candidates must show:

```text
blocked_coinbase_reward_mismatch
coinbaseMatchesExpectedPoolWallet: false
```

Already-paid candidates must show:

```text
blocked_already_paid
```

### 7.4 Auto payment path

Automatic wallet payout may send only for eligible confirmed self-test candidates.

Expected destination:

```text
PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD
```

Each successful send must produce:

```text
txid
candidateId
wallet
amount
status: paid / paid_manual / paid_wallet_send
```

The exact status name may follow the current implementation, but it must be clear that the payment was completed and recorded.

### 7.5 API visibility

The payments API must show the completed payment record:

```bash
curl -s http://127.0.0.1:8080/api/payments | jq
```

Expected result:

```text
items contains txid, wallet, amount, block height/hash, and payment status
```

---

## 8. Bounded Verification Commands

### 8.1 Runtime status

```bash
./ops/scripts/live-stratum.sh drill-status
```

Expected during this self-test:

```text
real_submit_enabled: True
real_submit_send_budget: 1000000
real_submit_error_count: 0
```

### 8.2 Candidate outcomes

```bash
./ops/scripts/live-stratum.sh candidate-outcomes 40
```

Look for:

```text
candidate_outcome_status: chain-match-found
followup_status: match-found
```

If many submitted candidates are still not checked:

```bash
./ops/scripts/live-stratum.sh candidate-followup 80 --record
./ops/scripts/live-stratum.sh candidate-outcomes 80
```

### 8.3 Payout candidates

```bash
./ops/scripts/live-stratum.sh payout-candidates
```

Expected behavior:

```text
confirmed + coinbase match -> eligible / ready
coinbase mismatch -> blocked_coinbase_reward_mismatch
already paid -> blocked_already_paid
immature/orphan/unknown -> blocked
```

### 8.4 Payout review

```bash
./ops/scripts/live-stratum.sh payout-review
```

Expected behavior:

```text
only eligible confirmed coinbase-matched candidates are reviewable/payable
```

### 8.5 Wallet send preflight

```bash
./ops/scripts/live-stratum.sh payout-wallet-send-preflight
```

Expected behavior:

```text
send_would_be_allowed: true
```

only when candidate is confirmed, coinbase-matched, unpaid, and pays the expected self-test wallet.

### 8.6 Payments API

```bash
curl -s http://127.0.0.1:8080/api/payments | jq
```

Expected behavior:

```text
completed payment records appear after txid is recorded
```

---

## 9. Runtime Environment Check

Before interpreting new submitted candidates, verify the active runtime environment:

```bash
grep -E 'PEPEPOW_POOL_CORE_REWARD_ADDRESS|PEPEPOW_ENABLE_REAL_SUBMITBLOCK|PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS|PEPEPOW_ENABLE_REAL_WALLET_PAYOUT' \
  .runtime/live-stratum/launch.env
```

Expected:

```bash
PEPEPOW_POOL_CORE_REWARD_ADDRESS=PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1000000
PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true
```

If `PEPEPOW_POOL_CORE_REWARD_ADDRESS` is missing from active runtime env, future blocks may not pay the intended pool reward wallet even if the code fix is present.

---

## 10. Operational Boundary

This self-test mode is allowed because:

```text
operator controls the miner
operator controls the pool reward wallet
operator controls the payout destination wallet
```

This does not automatically approve public automatic payout for unrelated community miners.

Before opening broader public payout capability, create a separate public payout readiness document that verifies:

```text
coinbase reward correctness
confirmed lifecycle correctness
round accounting correctness
payout amount correctness
duplicate payment protection
unexpected wallet handling
public wording
rollback behavior
```

---

## 11. What Must Not Be Changed During This Self-Test

Do not remove or weaken:

```text
blocked_coinbase_reward_mismatch
blocked_already_paid
immature/orphan/unknown blocking
coinbaseMatchesExpectedPoolWallet check
expected pool reward wallet check
txid recording
payment action logging
```

Do not treat old script-51 candidates as payable.

Do not expose wallet RPC publicly.

Do not add public admin payout endpoints.

---

## 12. Suggested Follow-Up After a Successful New Block

After a new candidate reaches `chain-match-found`, inspect the actual coinbase output:

```bash
H=<matched_height>
HASH=$(PEPEPOW-cli getblockhash "$H")
PEPEPOW-cli getblock "$HASH" 2 | jq -r '
  .tx[0].vout[] |
  {
    value,
    addresses: (.scriptPubKey.addresses // []),
    address: (.scriptPubKey.address // null),
    asm: (.scriptPubKey.asm // null),
    type: (.scriptPubKey.type // null)
  }'
```

Expected miner reward recipient:

```text
PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
```

Then regenerate payout candidates:

```bash
./ops/scripts/live-stratum.sh payout-candidates
```

Only if the candidate is confirmed, coinbase-matched, unpaid, and points to the expected self-test miner wallet should auto payment proceed.

---

## 13. Cross-Reference

Related earlier milestone:

```text
docs/benchmarks/2026-06-05-controlled-submitblock-success.md
```

That document records the earlier controlled submitblock success under a bounded MAX_SENDS=1 model.

This document supersedes the earlier default-off operational assumption only for the current private operator-owned self-test phase.
