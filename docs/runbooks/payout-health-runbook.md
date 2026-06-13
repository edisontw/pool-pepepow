# PEPEPOW Pool Payout Health Runbook

## Purpose

This document records the current payout recovery baseline and the low-token operating rules for future payout checks. It is intended to prevent repeated broad debugging, full test runs, large runtime scans, and unnecessary manual payout actions.

## Current Payout Baseline

The large unpaid payout backlog was caused mainly by confirmed pool rewards that were coinbase-matched but missing round/share attribution.

The backlog was cleared using an operator-approved backfill override to the current active miner wallet:

```text
PVKL38CAZxKX3tNczQCL9gN94i3SJ2LeNd
```

The pool reward wallet is:

```text
PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho
```

The operator-approved backfill is a rescue tool only. It must not be treated as normal payout logic.

## Normal Operation

Auto payment is enabled and should handle normal ready payouts.

Do not manually send small ready payouts unless auto payment is confirmed broken.

Normal payout should only pay candidates that pass existing guards:

* confirmed lifecycle
* coinbase matches expected pool wallet
* not orphan
* not immature
* not unconfirmed
* not already paid
* not coinbase mismatch
* valid wallet
* amount above minimum payout
* MAX_SENDS enforced
* txid recorded

## Health Check Frequency

Run payout health check every 30–60 minutes.

The health check should refresh snapshots only:

```bash
./ops/scripts/live-stratum.sh candidate-followup 1000 --record
./ops/scripts/live-stratum.sh accepted-candidates
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
```

Then summarize:

* total candidates
* confirmed coinbase match count
* unpaid_ready count
* unpaid_ready_amount
* unpaid_blocked_missing_round_or_share count
* coinbase_mismatch_confirmed count
* orphan / immature / unconfirmed counts

## Alert Rules

### No action

No action is needed when:

```text
unpaid_ready < 5
coinbase_mismatch_confirmed == 0
missing attribution is stable and low
```

### Normal auto payment expected

If:

```text
unpaid_ready >= 1
```

do not manually pay immediately. Let the auto payment timer process it.

Only intervene if unpaid_ready keeps increasing across multiple timer cycles.

### Missing attribution warning

If:

```text
unpaid_blocked_missing_round_or_share >= 20
```

report a warning. Do not immediately backfill.

First classify whether the candidates are:

* real confirmed unpaid rewards
* orphan / -1 confirmations
* stale leftovers
* missing wallet attribution
* already paid but not reflected in summary

### Manual backfill rescue

Operator-approved backfill may be used only when all are true:

* confirmed
* coinbaseMatchesExpectedPoolWallet == true
* blockedReason is blocked_missing_round or missing_share_data
* not already paid
* not orphan
* not immature
* not unconfirmed
* not coinbase mismatch
* operator explicitly approves target wallet

Use:

```bash
PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true \
PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=100 \
PEPEPOW_MIN_PAYOUT=1000 \
PEPEPOW_AUTO_PAYOUT_ALLOW_ANY_WALLET=true \
PEPEPOW_OPERATOR_BACKFILL_UNATTRIBUTED_CONFIRMED=true \
PEPEPOW_OPERATOR_BACKFILL_WALLET=PVKL38CAZxKX3tNczQCL9gN94i3SJ2LeNd \
PEPEPOW_OPERATOR_BACKFILL_REASON=operator_approved_unattributed_confirmed_rewards \
./ops/scripts/live-stratum.sh auto-payout-once
```

Do not leave operator backfill permanently enabled.

## Commands to Avoid

Do not run full tests during routine payout monitoring.

Avoid:

```bash
PYTHONPATH=ops/scripts python3 -m unittest tests.test_payout_accounting
```

unless code was modified.

Do not scan runtime JSONL broadly.

Avoid:

```bash
cat .runtime/live-stratum/*.jsonl
rg keyword .runtime/live-stratum/
pandas.read_json(...)
```

Use snapshots and bounded summaries only.

## Minimal Report Format

Use this format:

```text
Done:
Changed:
Test:
Result:
- unpaid_ready:
- unpaid_ready_amount:
- unpaid_blocked_missing_round_or_share:
- coinbase_mismatch_confirmed:
- action needed:
Next:
```

## Current Standing Rule

If auto payment is enabled, do not manually pay small ready items.
Manual intervention is only for growing backlog, coinbase mismatch, or confirmed missing-attribution buildup.
