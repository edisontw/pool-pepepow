# 2026-06-09 First Auto Wallet Payout Self-Test

Date: 2026-06-09  
Status: Completed  
Scope: Private operator-owned sustained submit and automatic wallet payout self-test

---

## 1. Summary

This document records the first successful end-to-end automatic wallet payout self-test for the PEPEPOW community pool.

The test completed the full live pool loop:

```text
miner shares
-> block candidate
-> submitblock
-> chain match
-> coinbase reward to configured pool wallet
-> payout candidate generation
-> payout threshold pass
-> wallet send
-> txid recorded
```

This milestone is limited to the private self-test environment where the operator controls the mining wallet, pool reward wallet, and payout destination wallet.

It is not yet a public automatic payout readiness statement for unrelated community miners.

---

## 2. Confirmed Pool Block

Confirmed candidate:

```text
candidateId: 00000006480127857d416580516f1b491bdf279080f73e5d94950a65dddb632d
blockHash:   00000006480127857d416580516f1b491bdf279080f73e5d94950a65dddb632d
height:      4588816
job_id:      job-00000000000000c9
candidate_timestamp: 2026-06-09T11:39:31Z
followup_status: match-found
followup_checked_at: 2026-06-09T12:29:41Z
followup_observed_height: 4588816
followup_note: candidate-block-hash-found-on-local-chain
```

Explorer coinbase recipients for block `4588816`:

```text
PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho    4,387.50 PEPEW
PJTnEVfmLqEYJLbGnT5GidRfMZcUHpB1q3    2,362.50 PEPEW
PHjJrmyDGCAjQFsbiucsC1Ex1nPbu8hgiC      250.00 PEPEW
```

This confirmed that the configured pool reward wallet was used correctly:

```text
PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
```

---

## 3. Payout Candidate Classification

`payout-candidates` classified the block as confirmed and coinbase-matched:

```json
{
  "candidateId": "00000006480127857d416580516f1b491bdf279080f73e5d94950a65dddb632d",
  "height": 4588816,
  "lifecycleStatus": "confirmed",
  "status": "ready_for_manual_review",
  "blockedReason": null,
  "coinbaseMatchesExpectedPoolWallet": true,
  "payouts": [
    {
      "amount": 4343.625,
      "baseAmount": 4343.625,
      "carryInAmount": 0,
      "carrySourceCandidateIds": [
        "00000006480127857d416580516f1b491bdf279080f73e5d94950a65dddb632d"
      ],
      "carrySourceCount": 1,
      "status": "pending_manual_payment",
      "wallet": "PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD",
      "weight": 0.8099999999999892
    }
  ]
}
```

Payout amount:

```text
4343.625 PEPEW
```

Destination wallet:

```text
PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD
```

---

## 4. Threshold Adjustment

The payout helper uses:

```text
PEPEPOW_MIN_PAYOUT
```

Default behavior was:

```text
PEPEPOW_MIN_PAYOUT=100000.0
```

At first, the block payout was classified as:

```text
below_threshold_carried
```

For the self-test, the threshold was temporarily lowered to:

```bash
PEPEPOW_MIN_PAYOUT=1000
```

After regenerating payout candidates with the lower threshold, the payout item became:

```text
pending_manual_payment
```

---

## 5. Wallet Send Preflight

Preflight command:

```bash
./ops/scripts/live-stratum.sh payout-wallet-send-preflight \
  --candidate-id 00000006480127857d416580516f1b491bdf279080f73e5d94950a65dddb632d \
  --wallet PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD \
  --amount 4343.625
```

Preflight result:

```text
preflight_status: preflight_ok
real_wallet_payout_enabled: false
max_sends: 1
send_would_be_allowed: false
send_attempted: false
send_sent: false
candidate_id: 00000006480127857d416580516f1b491bdf279080f73e5d94950a65dddb632d
wallet: PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD
amount: 4343.625
artifact_path: /home/ubuntu/pool-pepepow/.runtime/live-stratum/payout-wallet-send-preflight-result.json
```

Interpretation:

- Candidate, wallet, and amount passed preflight validation.
- Send remained blocked because `PEPEPOW_ENABLE_REAL_WALLET_PAYOUT` was not enabled for preflight.

---

## 6. Automatic Wallet Send

Send command:

```bash
PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true \
PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=1 \
PEPEPOW_MIN_PAYOUT=1000 \
./ops/scripts/live-stratum.sh payout-wallet-send-once \
  --candidate-id 00000006480127857d416580516f1b491bdf279080f73e5d94950a65dddb632d \
  --wallet PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD \
  --amount 4343.625
```

Send result:

```text
send_once_status: sent_recorded
real_wallet_payout_enabled: true
max_sends: 1
send_attempted: true
send_sent: true
candidate_id: 00000006480127857d416580516f1b491bdf279080f73e5d94950a65dddb632d
wallet: PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD
amount: 4343.625
txid: 50152e64ca2654d80f160e17fb5498a6a0e63e5b35105745559ddf1949e3ffee
artifact_path: /home/ubuntu/pool-pepepow/.runtime/live-stratum/payout-wallet-send-once-result.json
```

Successful payout txid:

```text
50152e64ca2654d80f160e17fb5498a6a0e63e5b35105745559ddf1949e3ffee
```

---

## 7. What This Proves

This self-test proves:

1. Sustained submit can produce chain-matched pool blocks.
2. The configured pool reward wallet is correctly used in the coinbase output for new blocks.
3. `payout-candidates` can classify a confirmed, coinbase-matched candidate as reviewable.
4. Lowering `PEPEPOW_MIN_PAYOUT` allows small self-test payouts to pass threshold.
5. `payout-wallet-send-preflight` validates the exact candidate, wallet, and amount.
6. `payout-wallet-send-once` can execute one guarded wallet payout and record the txid.
7. `PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=1` limits the run to a single send.

---

## 8. What This Does Not Prove

This milestone does not prove broader public payout readiness.

Still not fully validated for public miners:

- public automatic payout policy
- multi-wallet payout batching
- larger miner population behavior
- long-term balance carry policy
- unexpected wallet handling beyond the current self-test wallet
- public payout wording and expectations
- scheduled hourly payout operation

This milestone should be treated as a private operator-owned automatic payout self-test success.

---

## 9. Required Safety Guards That Must Remain

The following guards must remain active:

```text
blocked_coinbase_reward_mismatch
blocked_already_paid
immature/orphan/unknown blocking
coinbaseMatchesExpectedPoolWallet check
expected pool reward wallet check
MAX_SENDS limit
txid recording
payment action logging
```

Old candidates that did not pay the configured pool wallet must remain blocked.

---

## 10. Recommended Self-Test Runtime Policy

Suggested near-term self-test settings:

```bash
PEPEPOW_MIN_PAYOUT=1000
PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=5
```

Suggested cadence:

```text
Run payout review/send no more than once per hour during self-test.
```

Reason:

- small payouts are useful for community testing
- hourly batch behavior avoids excessive tiny transactions
- low miner count should not create meaningful CPU/RAM pressure
- wallet/transaction fragmentation stays bounded

---

## 11. Follow-Up Patch Completed

After the successful send, Codex fixed `PEPEPOW_MIN_PAYOUT` preservation in:

```text
ops/scripts/live-stratum.sh
```

Patch summary:

```text
Added MIN_PAYOUT defaults/load/write path so:
PEPEPOW_MIN_PAYOUT=1000 ./ops/scripts/live-stratum.sh systemd-restart
writes PEPEPOW_MIN_PAYOUT=1000 into launch.env.
```

Validation reported:

```text
bash -n ops/scripts/*.sh: passed
PYTHONPATH=ops/scripts python3 -m unittest tests.test_payout_accounting: passed, 91 tests
git diff --check: passed
```

Suggested host command after patch:

```bash
PEPEPOW_MIN_PAYOUT=1000 ./ops/scripts/live-stratum.sh systemd-restart
```

---

## 12. Suggested Commit

Commit title:

```text
Record first auto wallet payout self-test
```

Commit body:

```text
Record the 2026-06-09 PEPEPOW pool automatic wallet payout self-test.

Document the first confirmed post-restart pool block that paid the configured pool reward wallet, passed payout candidate classification, cleared the lowered self-test payout threshold, and completed a guarded wallet send.

Recorded txid:
50152e64ca2654d80f160e17fb5498a6a0e63e5b35105745559ddf1949e3ffee

This milestone is scoped to operator-owned private self-test conditions and does not claim public automatic payout readiness.
```

---

## 13. Final Result

```text
Status: SUCCESS
Block height: 4588816
Pool reward wallet: PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
Payout wallet: PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD
Amount: 4343.625 PEPEW
TXID: 50152e64ca2654d80f160e17fb5498a6a0e63e5b35105745559ddf1949e3ffee
```
