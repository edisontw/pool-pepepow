# Wallet Payout Automation Readiness — 2026-06-07

## Purpose

This benchmark note documents the current PEPEPOW wallet payout automation readiness state and the safe operator flow before any real wallet payout send is attempted.

This is a documentation-only readiness record. It does not authorize a real wallet payout send.

## Current completed state

The payout system is ready for guarded operator-driven verification, with the following pieces completed:

- Manual payout accounting works and remains the canonical manual fallback.
- Balance carry for below-threshold payouts works and is included in payout review/accounting.
- `payout-wallet-dry-run` works as a no-send payout intent and wallet-balance validation layer.
- `PEPEPOW_WALLET_CLI` is persisted for live-stratum payout tooling.
- `payout-wallet-send-preflight` exists and validates a specific candidate, wallet, and amount without sending funds.
- `payout-wallet-send-once` exists as a guarded one-shot wrapper for a single explicitly authorized send.
- Real wallet payout remains disabled by default and should remain disabled unless a real send drill is explicitly authorized.
- There is no cron, no worker, no public API/frontend control, and no `sendmany` payout automation.

## Safety flags

The expected safe live wallet payout configuration is:

```bash
PEPEPOW_WALLET_CLI=/home/ubuntu/PEPEPOW-cli
PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=false
PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=1
```

The `MAX_SENDS` boundary is intentionally one send. Values other than `1` should block guarded send and preflight flows.

## Normal operator flow

Use this sequence for normal payout review and no-send validation:

```bash
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
./ops/scripts/live-stratum.sh payout-wallet-dry-run
./ops/scripts/live-stratum.sh payout-wallet-send-preflight \
  --candidate-id <id> \
  --wallet <wallet> \
  --amount <amount>
```

The preflight step must use a real ready payout candidate, the exact wallet in that candidate payout, and the exact expected amount.

## Real send boundary

Do not run a real send unless it has been explicitly authorized by the operator on MN5.

When a real send drill is explicitly authorized:

- Use one real ready candidate only.
- Keep `PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=1`.
- Run `payout-wallet-send-preflight` first and require `preflight_ok` before any send.
- Use `payout-wallet-send-once` only after `preflight_ok`.
- Do not use dummy candidate IDs, dummy wallets, or dummy amounts for a real send.
- Do not use `sendmany`.
- Do not use wallet unlock or `walletpassphrase`.
- Do not use cron or worker automation.
- Do not use public API or frontend controls for real sends.

The guarded send boundary is intentionally manual and one-shot.

## Expected safe artifact states

### Dry-run artifact

Expected safe dry-run fields:

```json
{
  "mode": "dry_run",
  "realSendEnabled": false,
  "walletBalanceReadOk": true
}
```

If the local environment cannot reach the wallet CLI/RPC, `walletBalanceReadOk` may be `false`; that is safe and should block payout readiness until resolved.

### Preflight artifact

Expected preflight fields for any preflight run:

```json
{
  "mode": "send_preflight",
  "sendAttempted": false,
  "sendSent": false
}
```

A successful ready-to-send preflight should report `status: preflight_ok` and `sendWouldBeAllowed: true`. A failed preflight should report a blocking status such as `blocked_candidate_not_found`, `blocked_amount_mismatch`, `blocked_already_paid`, `blocked_wallet_balance_unreadable`, `blocked_insufficient_balance`, `blocked_invalid_address`, or `blocked_invalid_send_budget`.

### Send-once disabled artifact

With real wallet payout disabled, the guarded send-once wrapper should not send and should report:

```json
{
  "status": "blocked_real_wallet_payout_disabled",
  "sendAttempted": false,
  "sendSent": false
}
```

## Current boundary

Real payout send has not yet been executed through the guarded wallet payout send wrapper.

The first real send drill still requires manual operator authorization on MN5, using one real ready candidate after a `preflight_ok` result.
