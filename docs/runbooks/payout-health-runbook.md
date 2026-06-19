# PEPEPOW Pool Payout Health Runbook

## Purpose

This document records the current payout recovery baseline and the low-token operating rules for future payout checks. It is intended to prevent repeated broad debugging, full test runs, large runtime scans, unnecessary manual payout actions, and confusion between raw candidate status and actual payable rows.

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

Current expected live payout flags:

```text
real_wallet_payout_enabled: true
max_sends: 200
```

Do not disable these flags just because there are no currently ready rows. They are the current operating baseline unless the operator explicitly changes them.

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

## One-Screen Decision Rule

Use `payout-review` as the source of truth. Do not use raw outer candidate status alone to decide whether payment is stuck.

### OK / No Action

No payout action is needed when all are true:

```text
ready_payment_total: 0.0
normal_auto_ready_rows: 0
normal_auto_ready_total: 0.0
manual_review_only_rows: 0
malformed_ready_rows: 0
carry_audit_status: ok
```

`already_paid_rows > 0` is also OK when the skip reason is:

```text
skipped_rows_by_reason: {"blocked_already_paid": N}
```

That means source rows are already covered by aggregate or recorded payments.

### Ignore for Payment Decisions

Do not treat these by themselves as payout backlog:

```text
ready_for_manual_review: N
ready_count: N
ready_amount: 0.0
```

Raw `ready_for_manual_review` is an outer candidate status. It may include rows that are already paid, carried below threshold, manual-review-only, or otherwise not payable. The actionable fields are `normal_auto_ready_rows`, `normal_auto_ready_total`, `manual_review_only_rows`, and `malformed_ready_rows`.

### Auto Payment Expected

If:

```text
normal_auto_ready_rows > 0
normal_auto_ready_total > 0
```

let the auto payment path process it. Do not manually pay immediately.

Only investigate if the values remain non-zero after multiple auto-payout cycles.

### Code Fix Needed

Patch classification/reporting only if any are true:

```text
malformed_ready_rows > 0
carry_audit_status != ok
normal_auto_ready_rows > 0 but the same rows are already paid
```

Do not change payout eligibility or wallet flags unless there is a clear safety or accounting bug.

### Manual Review / Backfill Warning

Investigate, but do not immediately backfill, when:

```text
manual_review_only_rows > 0
missing_share_data >= 20
blocked_missing_miner_reward_output increases in recent confirmed rows
blocked_coinbase_reward_mismatch increases in recent confirmed rows
```

First classify whether the candidates are real confirmed unpaid rewards, stale leftovers, already paid rows, missing attribution, or non-pool coinbase outputs.

## Health Check Frequency

Run payout health check every 30-60 minutes when actively monitoring.

The health check should refresh snapshots only:

```bash
./ops/scripts/live-stratum.sh candidate-followup 1000 --record
./ops/scripts/live-stratum.sh accepted-candidates
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
```

For routine monitoring, the minimum fields to record are:

```text
ready_payment_total
normal_auto_ready_rows
normal_auto_ready_total
manual_review_only_rows
malformed_ready_rows
already_paid_rows
skipped_rows_by_reason
below_threshold_carry_total
wallet_carry_count
blocked_candidates
carry_audit_status
real_wallet_payout_enabled
max_sends
```

Optional blocked-reason summary is useful only if one of the decision rules above triggers.

## Manual Backfill Rescue

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

Use only for a confirmed rescue case:

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
- ready_payment_total:
- normal_auto_ready_rows:
- normal_auto_ready_total:
- manual_review_only_rows:
- malformed_ready_rows:
- already_paid_rows:
- skipped_rows_by_reason:
- carry_audit_status:
- real_wallet_payout_enabled:
- max_sends:
- action needed:
Next:
```

## Current Standing Rule

If auto payment is enabled, do not manually pay small ready items. Manual intervention is only for growing normal-auto backlog, coinbase mismatch, confirmed missing-attribution buildup, or classifier/audit warnings.
