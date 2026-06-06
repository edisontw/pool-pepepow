# Milestone: First Manual Payout Recorded - PEPEPOW Pool

**Date:** 2026-06-06  
**Status:** Completed  
**Milestone:** Successful execution and verification of the manual payout flow.

---

## 1. Overview of the Manual Payout

On 2026-06-06, the pool operator successfully executed the first manual payout for two eligible blocks confirmed on the blockchain. 
The manual payout process was completely external to the pool scripts. The pool scripts did not send any funds, and absolutely no wallet RPC was used or invoked by any of the payout scripts.

A total of **13,860 PEPEPOW** was paid out manually to miner wallets.

### Recorded Transactions
The following two payment records were recorded in the pool accounting log (`payment-actions.jsonl`) with real txids:

1. **Block Height: 4573193**
   - **Candidate Hash:** `000000158d4880a187ec04e02c96af5e977ca3c552e5f2e0a9536ec5411c99a2`
   - **Wallet Address:** `PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD`
   - **Amount:** `6,930.0 PEPEPOW`
   - **TXID:** `1dd1077fe24c140e6890313230632f2556e9069116e88903d97a1d9080b55381`

2. **Block Height: 4573284**
   - **Candidate Hash:** `00000007bb3b63116d0fac877f97ea45ba47b2c9759aadf81b5e8d2a9b18daf1`
   - **Wallet Address:** `PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD`
   - **Amount:** `6,930.0 PEPEPOW`
   - **TXID:** `c7b439336d9d326610a09404efb8de4104a1532d7d8ac46629bf61e89b56540e`

---

## 2. System Behavior & Verification

### Payments API
The payments snapshot endpoint `/api/payments` successfully displays both manual payment records along with their respective amounts, wallets, and txids.

### Preventative Double-Spend Protection
With the latest safety fix, already-paid candidates are dynamically blocked as `blocked_already_paid`. When the payout generator is executed, it detects these block-wallet matches in the action logs and immediately blocks them from being marked ready/payable or from producing pending payout entries.

### Candidate Isolation
All other candidates remain blocked under their appropriate statuses (e.g. `orphan_block` or `unconfirmed_status_candidate_recorded`) and are completely non-payable.

---

## 3. Safety Boundary Enforcement

To protect the integrity of the pool assets, the following architectural boundaries are strictly enforced:
- **No Automatic Payout:** Payouts can only be processed via deliberate operator intervention.
- **No Wallet Automation:** All transfers happen through external wallet tooling.
- **No Balance Carry:** Complex balance rollover logic is kept out of scope to avoid database dependencies.
- **No Public Admin Controls:** Admin payout APIs or endpoints are not exposed to the public.
- **No Payout from Orphan/Unconfirmed Blocks:** Blocks are validated dynamically via daemon confirmations, preventing payout on orphaned chains.
