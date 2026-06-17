# PEPEPOW Pool Troubleshooting

This page covers operator triage for the wallet watchdog and payout safety flow. Keep checks bounded and snapshot-based.

## Wallet Watchdog Reports Warning

Meaning: wallet balance increased more than expected from confirmed pool block accounting minus recorded outgoing payments.

Immediate response:

```bash
./ops/scripts/live-stratum.sh pool-wallet-watchdog --format human
./ops/scripts/live-stratum.sh accepted-candidates
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
./ops/scripts/live-stratum.sh payment-audit --format human
```

Check:

- whether a newly confirmed pool block was not present in the previous accepted-candidates snapshot
- whether a manual or external wallet transfer occurred outside the pool accounting flow
- whether payment actions and payment snapshot disagree
- whether the pool fee or reward assumptions changed between watchdog runs

Do not enable or continue real wallet payout while the watchdog is warning.

## Wallet Watchdog Reports Critical

Meaning: the watchdog could not read wallet balance or could not write a valid snapshot.

Check:

- explorer access from the host
- wallet address configured for the watchdog
- runtime directory permissions
- `.runtime/live-stratum/pool-wallet-watchdog.json`
- stderr from the command invocation

Re-run with human output:

```bash
./ops/scripts/live-stratum.sh pool-wallet-watchdog --format human
```

Do not treat a critical watchdog result as a payout approval.

## First Watchdog Run Says Baseline

This is expected. The first run records current balance and known accounting IDs. It cannot compare deltas until a later run.

Run it again after the next confirmed block or payment, or wait for the scheduled timer.

## Payout Candidate Is Not Ready

Use the review commands:

```bash
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
```

Common blocked states:

- orphan block
- immature block
- unconfirmed block
- coinbase mismatch
- already paid
- missing round or share attribution
- payout below `PEPEPOW_MIN_PAYOUT`

Do not bypass blocked states during normal operation.

## Real Wallet Send Is Blocked

Check the payout safety flags used for the exact command invocation:

```text
PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true
PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=1
PEPEPOW_MIN_PAYOUT=<intended minimum>
PEPEPOW_POOL_FEE_PERCENT=<intended fee percent>
```

If using `auto-payout-once`, also check:

```text
PEPEPOW_AUTO_PAYOUT_MAX_SENDS=<intended pass limit>
```

Then run preflight before any send:

```bash
./ops/scripts/live-stratum.sh payout-wallet-send-preflight \
  --candidate-id <candidateId> \
  --wallet <wallet> \
  --amount <amount>
```

Do not raise send limits or enable open-wallet behavior to get around a failed preflight. Fix the mismatch first.

## After Payout Looks Wrong

Stop payout sends and run:

```bash
./ops/scripts/live-stratum.sh refresh-payment-confirmations
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
./ops/scripts/live-stratum.sh payment-audit --format human
./ops/scripts/live-stratum.sh pool-wallet-watchdog --format human
curl -s http://127.0.0.1:8080/api/payments | jq
```

Check:

- txid exists and belongs to the intended payout
- txid was recorded once
- wallet address matches the candidate
- amount matches the candidate
- candidate is now blocked as already paid or absent from ready payouts
- watchdog returns `ok`

Do not manually edit payment logs or snapshots during live wallet operations. If accounting repair is required, do it in a separate maintenance window.

## Commands To Avoid During Wallet Triage

Avoid unbounded runtime reads:

```bash
cat .runtime/live-stratum/*.jsonl
rg keyword .runtime/live-stratum/
pandas.read_json(...)
```

Use bounded reads only when a specific file and hypothesis are known:

```bash
tail -n 200 .runtime/live-stratum/payment-actions.jsonl
rg "txid_or_candidate_id" .runtime/live-stratum/payment-actions.jsonl | tail -n 50
```

