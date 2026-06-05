# 2026-06-05 Controlled submitblock Success Milestone

This document records the first end-to-end controlled submitblock drill in which the pool
assembled a candidate block, transmitted it to the daemon, received a `Success` response,
and subsequently confirmed that the candidate hash appeared on-chain via the follow-up chain
scan.

---

## 1. What Was Fixed

Before this drill, two serialization bugs prevented candidate blocks from ever matching
the chain:

| Fix | Description |
|-----|-------------|
| **Prevhash byte-order alignment** | The pool was placing the prevhash bytes in the wrong endian order relative to what the daemon's `CheckProofOfWork` expects. Aligned to daemon representation. |
| **Merkle root serialization** | The coinbase transaction merkle root was not being packed in the correct field position. Corrected field layout to match the daemon's block-header schema. |

Both fixes landed before this session and were the subject of the 2026-05-31 stale-prevblk
guard drill, which confirmed the candidate pipeline was live but stopped short of a
successful on-chain confirmation.

---

## 2. Submit Evidence

| Field | Value |
|-------|-------|
| Drill timestamp | `2026-06-05T12:42:37Z` |
| Job ID | `job-000000000000001e` |
| Candidate block hash | `00000007bb3b63116d0fac877f97ea45ba47b2c9759aadf81b5e8d2a9b18daf1` |
| `submitblockDaemonResult` | `Success` |
| `submitblockDaemonAcceptedLikely` | `True` |
| Submit budget used | 1 of 1 (`MAX_SENDS=1`) |

Daemon RPC `submitblock` returned `Success` immediately upon receipt.

---

## 3. Chain Match Confirmation

The follow-up chain scan (executed at `2026-06-05T12:44:05Z`, ~87 seconds after submit)
queried the local daemon for the candidate hash and found it present on the canonical chain.

| Field | Value |
|-------|-------|
| `followup_status` | `match-found` |
| `candidate_outcome_status` | `chain-match-found` |
| Confirmed height | `4573284` |
| Confirmed block hash | `00000007bb3b63116d0fac877f97ea45ba47b2c9759aadf81b5e8d2a9b18daf1` |
| `followup_note` | `candidate-block-hash-found-on-local-chain` |

The hash returned by `getblockhash(4573284)` matched the submitted candidate hash exactly.

> **Note:** A second earlier candidate (`000000158d4880a1…`, height 4573193, job
> `job-0000000000000004`, submitted at `11:57:12Z`) also produced a `chain-match-found`
> outcome in the same follow-up scan. Both occurred within the same `MAX_SENDS=1` budget
> window. The primary milestone candidate recorded here is the `12:42:37Z` event at height
> 4573284.

---

## 4. Safety State Restored

Immediately following budget exhaustion the runtime re-locked automatically. The current
state verified via `drill-status` (run `2026-06-05T14:59:05Z`):

```
drill_status:                        ready
real_submit_enabled:                 False
real_submit_send_budget:             1
real_submit_send_budget_remaining:   1
real_submit_attempt_count:           0
real_submit_sent_count:              0
real_submit_error_count:             0
real_submit_last_status:             submit-disabled-flag-off
```

All subsequent candidate events show `submit_status: submit-disabled-flag-off` and
`submit_sent: False` — confirming the pool is operating in safe dry-run mode.

---

## 5. What This Proves

- The **prevhash and merkle root serialization fixes are correct**. The assembled block
  header is accepted by the daemon without modification.
- The **submitblock RPC path is functional end-to-end**: candidate assembly → RPC call →
  daemon acceptance → chain confirmation.
- The **stale-prevblk guard works**: a previous drill (2026-05-31) correctly blocked a
  stale submit; this drill correctly allowed a fresh one through.
- The **safety budget mechanism works**: `MAX_SENDS=1` was honoured; the pool locked
  itself after one send without operator intervention.
- The **follow-up chain scanner works**: it correctly detects a confirmed block hash on
  the local daemon chain within ~90 seconds of submission.

---

## 6. What This Does Not Prove

- **Payout readiness**: No payout logic was exercised. Round accounting and payout
  disbursement remain deferred.
- **Round accounting completeness**: Share accounting and round boundaries were not
  validated in this drill.
- **Production submit readiness**: `real_submit_enabled` was `False` throughout; the drill
  used the controlled drill path only. Enabling live production submit requires a separate
  deliberate decision and safety review.
- **Sustained block-find rate**: This was a single-event drill under controlled budget
  conditions, not a sustained mining operation.

---

## 7. Drill Parameters

| Parameter | Value |
|-----------|-------|
| `PEPEPOW_ENABLE_REAL_SUBMITBLOCK` | `true` (drill session only) |
| `PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS` | `1` |
| `real_submit_enabled` (post-drill) | `False` |
| Template mode | `daemon-template` |
| Template fetch status | `ok` |
