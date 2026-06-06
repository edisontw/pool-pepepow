# Round Accounting Design Note - PEPEPOW Pool

This note details the core design principles and safety boundaries for the read-only PEPEPOW round accounting prototype.

## 1. Round Boundary
A **mining round** is the period of work dedicated to finding a block. 
- **Open Boundary**: A round is opened either when the pool begins operations (initial round) or immediately after the previous pool block is found.
- **Close Boundary**: A round is closed when the pool successfully submits an accepted candidate block that matches a block hash on the blockchain.
- **Chronological Sequence**: Candidate submissions are sorted by their submission timestamp to determine consecutive round intervals. For a given candidate block $B_i$ at submission time $T_i$ and preceding block $B_{i-1}$ at submission time $T_{i-1}$, the round interval is defined as $(T_{i-1}, T_i]$.

## 2. Share Attribution
Miner share submissions are attributed to the active mining round during which they were submitted.
- **Time-based Filtering**: Shares with submission timestamp $t$ are attributed to round $i$ if $T_{i-1} < t \le T_i$.
- **Strict Validity Checks**: To ensure fairness and security, the following shares are strictly excluded from round share calculations:
  - **Rejected Shares**: Shares not accepted by the Stratum protocol (`accepted: false`).
  - **Malformed Shares**: Shares with missing identity, missing timestamp, or corrupted JSON formatting.
  - **Low-difficulty Shares**: Shares with a target difficulty lower than the pool's configured minimum share difficulty floor (as defined by the assumed difficulty metadata).

## 3. Candidate / Block Lifecycle
Accepted pool candidates are tracked through the following lifecycle states:
- `candidate_recorded`: Candidate block submission recognized by the pool wrapper.
- `submit_accepted`: Submitted successfully to the daemon.
- `chain_match_found`: A matching block is detected on the blockchain, but confirmations are not yet resolved.
- `immature`: Matched on-chain with confirmations $> 0$ but less than the maturity threshold (100 blocks).
- `confirmed`: Matched on-chain and has reached at least 100 confirmations.
- `orphan`: The block candidate failed to match the active blockchain tip.

## 4. Immature / Orphan Safety
To prevent premature balance calculation and double-spending risks:
- **Immature Safety**: Rounds corresponding to blocks in the `immature` or `chain_match_found` states are explicitly marked as not payable (`payable: false`).
- **Orphan Safety**: Rounds corresponding to `orphan` blocks are invalid and marked as not payable (`payable: false`).
- **Confirmed Safety**: Confirmed rounds are still not payable because payout execution and balance management code do not exist in this prototype. To avoid misleading operators or miners, confirmed rounds MUST completely omit any balance, payable, earned, paid, or reward-ready fields.
