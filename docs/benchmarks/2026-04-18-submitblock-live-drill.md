# `submitblock` Live Drill Evidence

- Date: 2026-04-18
- Operator: Codex via terminal session
- Service version / commit: `d4aa7d2`
- `PEPEPOW_ENABLE_REAL_SUBMITBLOCK`: `false -> true -> false`
- `PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS`: `1`

## Preflight

- Timestamp: `2026-04-18T05:59:26Z`
- `templateModeEffective`: `daemon-template`
- `templateDaemonRpcReachable`: `true`
- `templateFetchStatus`: `ok`
- `realSubmitblockEnabled`: `false`
- `realSubmitblockSendBudget`: `1`
- `realSubmitblockSendBudgetRemaining`: `1`
- `realSubmitblockAttemptCount`: `0`
- `realSubmitblockSentCount`: `0`
- `realSubmitblockErrorCount`: `0`
- `realSubmitblockLastStatus`: `never-attempted`
- `submitAcceptedCount`: `3922`
- `submitRejectedCount`: `0`

## Observation

- Enable restart timestamp: `2026-04-18T05:59:36Z`
- Startup warning observed: `yes`
- Warning line: `2026-04-18 05:59:35,958 WARNING pepepow.stratum_ingress REAL submitblock ENABLED via PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true; block-target shares may call daemon submitblock; send_budget=1 remaining=1`
- Observation window: `2026-04-18T05:59:43Z` through `2026-04-18T06:00:59Z`
- `realSubmitblockLastStatus`: `never-attempted`
- `realSubmitblockAttemptCount`: `0`
- `realSubmitblockSentCount`: `0`
- `realSubmitblockErrorCount`: `0`
- `realSubmitblockLastAttemptAt`: `null`
- `realSubmitblockLastError`: `null`
- Accepted shares continued during enabled window: `yes`
- Accepted shares observed by end of enabled window: `292`

## Outcome

- Candidate reached `meetsBlockTarget`: `no`
- Real submit attempted: `no`
- Real submit sent: `no`
- Daemon result: `none`
- Rollback completed: `yes`
- Rollback restart timestamp: `2026-04-18T06:01:18Z`
- Post-rollback `realSubmitblockEnabled`: `false`
- Post-rollback `realSubmitblockSendBudgetRemaining`: `1`
- Post-rollback accepted shares observed through `2026-04-18T06:02:43Z`: `278`
- Post-rollback share status sample: `share-hash-invalid=265`, `share-hash-valid=13`
- Post-rollback real-submit sample: `submit-not-triggered=278`, `submitblockAttempted=false=278`, `submitblockSent=false=278`
- Post-rollback snapshot/API alignment: `yes`
- Post-rollback aligned API sample at `2026-04-18T06:02:54Z`: `realSubmitblockEnabled=false`, `realSubmitblockAttemptCount=0`, `realSubmitblockSentCount=0`, `realSubmitblockErrorCount=0`, `submitAcceptedCount=323`, `submitRejectedCount=0`, `submitShareHashValidationCounts.share-hash-invalid=308`, `submitShareHashValidationCounts.share-hash-valid=15`
- Notes: The drill stayed within the one-shot send budget guardrail, produced no candidate, made no daemon-side `submitblock` call, and returned cleanly to the default-off baseline with accepted shares continuing normally.
