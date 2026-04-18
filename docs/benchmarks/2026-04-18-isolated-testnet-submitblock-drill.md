# Isolated Testnet `submitblock` Drill

- Date: `2026-04-18`
- Approach: controlled low-difficulty environment
- Purpose: produce the first real block-candidate and real `submitblock` evidence under tightly controlled conditions without touching the production daemon or architecture

## Setup

- Isolated daemon:
  - binary: `/home/ubuntu/PEPEPOWd`
  - mode: `-testnet`
  - datadir: `/home/ubuntu/.tmp/pepepow-testnet-drill`
  - rpc: `127.0.0.1:18884`
  - config:
    - `server=1`
    - `daemon=1`
    - `listen=0`
    - `dnsseed=0`
    - `discover=0`
    - `connect=0`
    - `litemode=1`
    - `rpcuser=drill`
    - `rpcpassword=drillpass`
- Chain preparation:
  - `setgenerate true 1` on the isolated testnet daemon advanced the chain from genesis to height `587`
  - `mnsync next` was run until `mnsync status` reached `MASTERNODE_SYNC_FINISHED`
- Temporary pool ingress:
  - repo path: `/home/ubuntu/pool-pepepow/apps/pool-core`
  - bind: `127.0.0.1:39444`
  - runtime dir: `/home/ubuntu/.tmp/pepepow-testnet-stratum`
  - template mode: `daemon-template`
  - real submit: `enabled`
  - send budget: `1`

## Compatibility Note

- The isolated testnet `getblocktemplate` returned `masternode: {}` when no masternode payout output existed.
- A small compatibility fix now treats an explicitly empty payout object as “no payout outputs” during template normalization.
- This did not change share hashing, target comparison, or submit logic.

## Observed Candidate

- Stratum job:
  - `jobId = job-0000000000000001`
  - `target = 0000be2e00000000000000000000000000000000000000000000000000000000`
  - `difficulty = 1e-08`
- One-off isolated client:
  - login: `TESTWALLET.rig01`
  - found a block-target share in `51,655` hashes over `6.819s`
  - submit fields:
    - `extranonce2 = 00000001`
    - `nonce = 0000c9c6`
  - share hash / candidate block hash:
    - `000017861966e9a8c0cd19cadad080c01847a16c2ed3a63b3312093cc903df64`

## Evidence

- Temporary share evidence:
  - `/home/ubuntu/.tmp/pepepow-testnet-stratum/share-events.jsonl`
  - recorded:
    - `shareHashValidationStatus = share-hash-valid`
    - `meetsShareTarget = true`
    - `meetsBlockTarget = true`
    - `candidatePrepStatus = candidate-prepared-complete`
    - `submitblockDryRunStatus = dry-run-prepared-complete`
    - `submitblockRealSubmitStatus = submit-sent`
    - `submitblockAttempted = true`
    - `submitblockSent = true`
    - `submitblockDaemonResult = null`
- Temporary candidate evidence:
  - `/home/ubuntu/.tmp/pepepow-testnet-stratum/candidate-events.jsonl`
  - recorded one candidate event for the same block hash with:
    - `candidatePrepStatus = candidate-prepared-complete`
    - `submitblockDryRunStatus = dry-run-prepared-complete`
    - `realSubmitblockEnabled = true`
    - `submitblockRealSubmitStatus = submit-sent`
    - `followupStatus = not-checked`
- Temporary follow-up evidence:
  - `/home/ubuntu/.tmp/pepepow-testnet-stratum/candidate-followup-events.jsonl`
  - manual follow-up recorded:
    - `followupStatus = match-found`
    - `followupObservedHeight = 588`
    - `followupObservedBlockHash = 000017861966e9a8c0cd19cadad080c01847a16c2ed3a63b3312093cc903df64`
    - `followupNote = candidate-block-hash-found-on-local-chain`

## Result

- A real block-candidate was produced under the existing daemon-template path.
- The guarded real-submit path sent exactly one `submitblock(candidateBlockHex)` because:
  - `meetsBlockTarget = true`
  - candidate prep was complete
  - dry-run payload was complete
  - real submit was explicitly enabled
  - send budget was `1`
- The submitted block was accepted by the isolated daemon and became the best block at height `588`.

## Rollback

- Temporary stratum ingress on `127.0.0.1:39444` was stopped.
- Isolated testnet daemon on `127.0.0.1:18884` was stopped.
- Production daemon and production stratum remained:
  - `127.0.0.1:8834` active
  - `0.0.0.0:39333` active
  - `realSubmitblockEnabled = false`

## Final Production Baseline Recheck

- Rechecked at `2026-04-18T09:44:58Z`.
- `pepepow-pool-stratum.service` and `pepepow-pool-api.service` were both `active`.
- Listening sockets were back to the expected production baseline only:
  - `127.0.0.1:8834` daemon RPC
  - `127.0.0.1:8080` API
  - `0.0.0.0:39333` stratum
- No listener remained on the temporary drill ports `127.0.0.1:18884` or `127.0.0.1:39444`.
- `/api/health` reported:
  - `templateModeEffective = "daemon-template"`
  - `templateDaemonRpcStatus = "reachable"`
  - `templateFetchStatus = "ok"`
  - `realSubmitblockEnabled = false`
  - `realSubmitblockSendBudgetRemaining = 1`
  - `realSubmitblockAttemptCount = 0`
  - `realSubmitblockSentCount = 0`
  - `realSubmitblockErrorCount = 0`
- Fresh production accepted shares were still present with `activityLastShareAt = "2026-04-18T09:44:58Z"`.
