# 2026-08-11 Pure SOLO Mainnet Mining-to-Payout Milestone

This document records the first complete Pure SOLO production cycle for the
PEPEPOW community pool: external mining on the dedicated SOLO Stratum endpoint,
a naturally found mainnet block, real `submitblock`, lifecycle confirmation,
SOLO finder accounting, real wallet payout, and replay protection.

---

## 1. Production Path

```text
external GPU miner
→ pool.pepepow.net:39334
→ Pure SOLO Stratum
→ daemon-template job
→ valid block-target share
→ real submitblock
→ PEPEPOW mainnet block
→ candidate follow-up
→ confirmed/mature
→ SOLO finder payout
→ payment txid
→ replay guard
```

Pool Stratum on `39333` remained active and isolated throughout the test.

---

## 2. Mainnet Block Evidence

| Field | Value |
|---|---|
| Mining mode | `solo` |
| Finder wallet | `PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD` |
| Finder worker | `SOLOTEST` |
| Candidate hash | `00000000b6240c251676dfe0b7adb200ade3c891ee81d5d6621fa23e08cd79ae` |
| Mainnet height | `4845284` |
| Submit time | `2026-08-11T14:31:02Z` |
| `submitblock` result | `null` (accepted success semantics) |
| Chain match | `true` |

The candidate hash was subsequently read back from the local daemon at height
`4845284`, confirming the block was accepted onto the PEPEPOW main chain.

---

## 3. Lifecycle

The real candidate progressed through the normal SOLO lifecycle:

```text
submit_accepted
→ chain match
→ immature
→ confirmed
```

Automatic SOLO lifecycle refresh was integrated into the existing scheduled
payout refresh path. The candidate exceeded the configured payout maturity
threshold of 101 confirmations before payment.

---

## 4. Reward and Payout

The payout used the actual confirmed coinbase output belonging to the configured
pool reward address as the authoritative miner reward. The reward was not
hard-coded from a nominal block schedule.

| Field | Value |
|---|---|
| Pool reward address | `PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho` |
| Gross miner reward | `3737.5 PEPEW` |
| SOLO fee | `1.0%` |
| SOLO fee amount | `37.375 PEPEW` |
| Finder net payout | `3700.125 PEPEW` |
| Finder count | `1` |
| Payout weight mode | `solo_finder` |

Real payment transaction:

```text
13f9328373351c28dd26db339a50894b61379f0cfdf25745dfc170358a9251b7
```

The wallet transaction was verified as a send of `3700.125 PEPEW` to the finder
wallet above.

---

## 5. Replay Protection

The exact same payout command was invoked again after the successful send.
The second invocation returned:

```text
blocked_already_paid
```

No duplicate transaction was created.

Persistent candidate/payment action records, rather than only process-local send
budgets, are the primary duplicate-payment protection.

---

## 6. Pool / SOLO Isolation

Verified throughout the milestone:

- SOLO shares were absent from Pool share accounting.
- SOLO candidates did not create Pool round boundaries.
- SOLO candidates were excluded from Pool payout candidates.
- Pool payouts remained operational and separate.
- SOLO payment actions and payment snapshots remained under the isolated SOLO
  runtime path.
- Public Pool and SOLO API/miner views remained separate.

---

## 7. Production Operationalization

After the first one-shot validation, Pure SOLO was moved from drill behavior to
normal production operation.

Production behavior now uses:

- automatic natural block submission from the SOLO Stratum service
- private bounded submit ceilings
- automatic candidate lifecycle refresh
- automatic mature SOLO finder payout through the existing scheduled payout flow
- persistent replay/idempotency protection
- private wallet/daemon RPC only
- public snapshot/API visibility only

At the end of operationalization, the live configuration used bounded production
ceilings of:

```text
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1000
PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=200
```

These are runaway-loop ceilings, not per-block approval requirements. Persistent
candidate/payment records remain the core duplicate-send protection.

---

## 8. Public Surface

The public website/API now exposes separate Pure SOLO read-only views, including:

```text
GET /api/solo/summary
GET /api/solo/accepted-candidates
GET /api/solo/payments
GET /api/solo/miner/<wallet>
```

The public connection endpoints are:

```text
Pool Mining:      pool.pepepow.net:39333
Pure SOLO Mining: pool.pepepow.net:39334
```

Daemon RPC, wallet RPC, submit controls, payout controls, raw runtime logs, and
runtime configuration remain private.

---

## 9. What This Proves

This milestone validates the complete Pure SOLO mainnet path:

- external miner connectivity
- isolated SOLO share ingestion
- natural block-target detection
- real mainnet `submitblock`
- chain lifecycle tracking
- dynamic miner reward extraction
- 1% SOLO fee accounting
- single-finder payout
- real wallet transaction
- duplicate-payment prevention
- scheduled production operationalization
- Pool/SOLO accounting isolation

Pure SOLO is therefore no longer only a dry-run or candidate-preparation path; it
has completed a real mining-to-payout mainnet cycle.

---

## 10. Recovery Reference

The repository retains the pre-SOLO baseline tag:

```text
baseline/pre-pure-solo-20260811
```

This provides a stable recovery/reference point from before Pure SOLO was merged
into `main`.
