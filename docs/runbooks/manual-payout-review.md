# Manual Payout Review Runbook

This runbook guides pool operators through the process of generating, reviewing, manually executing, and recording manual payouts for pool-found blocks.

## Safety & Operations Warnings

> [!WARNING]
> **No Wallet RPC:** Under no circumstances should pool scripts attempt to invoke wallet RPC, unlock wallets, or trigger automatic transfers. All execution is strictly manual.
> **No Automatic Payout:** Automatic payout workers must remain disabled.
> **Do Not Pay Blocked Candidates:** Only candidates with `ready_for_manual_review` status are eligible. Never process payments for blocked candidates.
> **Do Not Pay Orphan/Unconfirmed Candidates:** Verify that candidates are not marked as an orphan block or in an unconfirmed state.
> **Do Not Record TXID Before Actual Transfer:** Never call the record-payment CLI command with a txid until the external wallet transfer has been fully sent and confirmed on the blockchain.

---

## 1. Preflight Checks

Before starting, ensure that:
1. The pool daemon is synced and running.
2. The stratum runtime is fully operational.
3. The operator has access to external wallet tooling (such as the `pepepow-cli` or a desktop wallet) with sufficient balance to cover payouts.

---

## 2. Generate Payout Candidates

To read the confirmed candidates and rounds from live stratum files and prepare the payout proposal:
```bash
./ops/scripts/live-stratum.sh payout-candidates
```
This command processes accepted candidates and rounds snapshots, querying the daemon RPC if necessary for confirmations and rewards, and produces `.runtime/live-stratum/payout-candidates.json`.

---

## 3. Review Ready Candidates

To display and review only candidates that are `ready_for_manual_review`:
```bash
./ops/scripts/live-stratum.sh payout-review
```
Alternatively, filter the output directly using Python or `jq`:
```bash
python3 -c '
import json
data = json.load(open(".runtime/live-stratum/payout-candidates.json"))
ready = [x for x in data.get("items", []) if x.get("status") == "ready_for_manual_review"]
for x in ready:
    print(f"Height: {x.get(\"height\")} | Hash: {x.get(\"blockHash\")} | Net Reward: {x.get(\"netReward\")}")
    for p in x.get("payouts", []):
        print(f"  -> Wallet: {p.get(\"wallet\")} | Amount: {p.get(\"amount\")}")
'
```

---

## 4. Manually Verify Payout Totals

1. Sum up the target amount for each ready candidate.
2. Confirm the fee calculation:
   $$\text{Net Reward} = \text{Gross Reward} \times \left(1 - \frac{\text{Pool Fee Percent}}{100}\right)$$
3. Verify that the sum of all payouts in a candidate matches the candidate's `netReward` exactly.

---

## 5. Manually Transfer Using External Wallet Tooling

Use `pepepow-cli` or your secure external wallet to transfer the exact amount to each miner's wallet address.
Example:
```bash
pepepow-cli sendtoaddress "PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD" 6930.00
```
Keep a record of the resulting Transaction ID (txid) for each transfer.

---

## 6. Record Payment

Only after the transaction has been sent externally, record the manual payment inside the pool accounting logs. Use the record-payment command for each payout in the ready candidate:
```bash
./ops/scripts/live-stratum.sh record-payment <candidate_hash> <wallet> <amount> <txid>
```
For example:
```bash
./ops/scripts/live-stratum.sh record-payment \
  000000158d4880a187ec04e02c96af5e977ca3c552e5f2e0a9536ec5411c99a2 \
  PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD \
  6930.0 \
  <actual_transaction_id_returned_from_wallet_here>
```

---

## 7. Verify Payments API

Verify that the recorded manual payment shows up on the public payments endpoint:
```bash
curl -s http://127.0.0.1:8080/api/payments | jq
```
It should return the newly recorded payment entry in the `items` list.

---

## 8. Rollback & Abort Guidance

If a candidate is blocked or if there is any mismatch in amounts or address mappings:
1. **Abort immediately:** Do not send funds if you detect any inconsistency.
2. **Re-run candidate generation:** Delete the local `.runtime/live-stratum/payout-candidates.json` file and regenerate it to ensure the state matches the block index.
3. If an incorrect payment was recorded in `payment-actions.jsonl` but not actually sent to the blockchain, you can clean up the actions file or revert the JSON snapshot write to prevent showing a false payment history.
