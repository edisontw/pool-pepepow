# PEPEPOW Pool Operator Guide

This guide covers the operator-only wallet watchdog and the guarded payout safety flow. It is documentation only; do not paste these examples into production environment files without an explicit operator change window.

## Wallet Watchdog

The wallet watchdog compares the pool wallet balance against accounting deltas from confirmed pool blocks and recorded outgoing payments. It writes:

```text
.runtime/live-stratum/pool-wallet-watchdog-state.json
.runtime/live-stratum/pool-wallet-watchdog.json
```

Run it manually from the repository root:

```bash
./ops/scripts/live-stratum.sh pool-wallet-watchdog
```

For human-only output:

```bash
./ops/scripts/live-stratum.sh pool-wallet-watchdog --format human
```

For machine-readable output:

```bash
./ops/scripts/live-stratum.sh pool-wallet-watchdog --format json
```

The first run records a baseline and exits successfully. Later runs compare current wallet balance to the previous sampled balance.

## Watchdog Output

`status: baseline`

The watchdog recorded the first balance sample. This is not an alert. Run it again after new confirmed blocks or payouts exist.

`status: ok`

The wallet balance delta is consistent with newly confirmed pool rewards and outgoing recorded payments. No payout action is implied.

`status: warning`

The wallet balance increased more than expected from the accounting inputs. Stop live wallet operations and investigate before enabling or continuing payout sends.

`status: critical`

The watchdog could not read the wallet balance or could not produce a valid snapshot. Treat this as a monitoring failure, not as proof of wallet safety.

Exit codes:

```text
0 = baseline or ok
1 = warning
2 = critical
```

## Suggested Schedule

Run the watchdog every 10-15 minutes during normal operation, and run it manually before and after any real wallet payout window.

Cron example:

```cron
*/15 * * * * cd /home/ubuntu/pool-pepepow && ./ops/scripts/live-stratum.sh pool-wallet-watchdog --format human >> .runtime/live-stratum/pool-wallet-watchdog.cron.log 2>&1
```

For systemd timer examples, see `docs/systemd-examples.md`.

## Payout Safety Flags

Real wallet payout commands must remain guarded by explicit environment flags.

`PEPEPOW_ENABLE_REAL_WALLET_PAYOUT`

Must be `true` for real wallet sends. Any other value should block sends.

`PEPEPOW_MIN_PAYOUT`

Minimum wallet payout amount. Candidates below this threshold are not eligible for immediate send and may be carried forward.

`PEPEPOW_POOL_FEE_PERCENT`

Pool fee percentage used when calculating miner net payout from confirmed rewards.

`PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS`

Hard limit for real wallet send operations in the guarded send path. Use a small value for live operations; `1` is the safest default for a manual send window.

`PEPEPOW_AUTO_PAYOUT_MAX_SENDS`

Auto payout pass limit used by `auto-payout-once`. Keep this low and aligned with the intended live payout window.

## Before Enabling Payout

Run these checks before any real wallet payout send:

```bash
./ops/scripts/live-stratum.sh candidate-followup 1000 --record
./ops/scripts/live-stratum.sh accepted-candidates
./ops/scripts/live-stratum.sh track-rounds
./ops/scripts/live-stratum.sh payout-carry
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
./ops/scripts/live-stratum.sh payout-wallet-dry-run
./ops/scripts/live-stratum.sh pool-wallet-watchdog --format human
```

Verify:

- daemon and wallet are synced
- candidate lifecycle is confirmed
- candidate coinbase matches the expected pool wallet
- candidate is not orphan, immature, unconfirmed, or already paid
- payout wallet and amount match the reviewed candidate
- amount is at or above `PEPEPOW_MIN_PAYOUT`
- pool fee matches `PEPEPOW_POOL_FEE_PERCENT`
- `PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS` is set to the intended small send count
- watchdog is `baseline` or `ok`, not `warning` or `critical`

## During Live Wallet Operations

Do not:

- restart wallet, daemon, Stratum, API, nginx, or payout timers mid-send
- edit production environment files
- change payout flags while a send command is running
- run broad runtime JSONL scans
- manually edit payout snapshots or action logs
- run more than one payout send process at the same time
- record a txid before the wallet send succeeds
- pay blocked, fallback, orphan, immature, unconfirmed, coinbase-mismatched, or already-paid candidates

## After Payout

Run:

```bash
./ops/scripts/live-stratum.sh refresh-payment-confirmations
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
./ops/scripts/live-stratum.sh payment-audit --format human
./ops/scripts/live-stratum.sh pool-wallet-watchdog --format human
curl -s http://127.0.0.1:8080/api/payments | jq
```

Verify:

- txid was recorded once
- paid candidate no longer appears as ready for payment
- payment snapshot and public payments API show the expected payment
- wallet balance delta is expected
- watchdog is `ok`
- no new `warning` or `critical` watchdog state exists

