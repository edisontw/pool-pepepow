# Controlled Live `submitblock`

This runbook is only for the existing daemon-template stratum ingress path.

## Scope

- Real `submitblock` remains default-off.
- This runbook does not change payout, round tracking, block lifecycle, API shape, frontend, nginx, or wrapper/systemd layout.
- This runbook assumes the current candidate-prep and dry-run path is already validated.

## Preflight

Verify all of the following before enabling real submit:

```bash
systemctl status pepepow-pool-stratum.service --no-pager --lines=20
curl -s http://127.0.0.1:8080/api/health | jq .
python3 - <<'PY'
import json
from pathlib import Path
path = Path('/home/ubuntu/pool-pepepow/.runtime/live-stratum/activity-snapshot.json')
meta = json.loads(path.read_text())['meta']
print('templateModeEffective=', meta.get('templateModeEffective'))
print('templateDaemonRpcReachable=', meta.get('templateDaemonRpcReachable'))
print('templateFetchStatus=', meta.get('templateFetchStatus'))
print('realSubmitblockEnabled=', meta.get('realSubmitblockEnabled'))
print('realSubmitblockLastStatus=', meta.get('realSubmitblockLastStatus'))
print('realSubmitblockAttemptCount=', meta.get('realSubmitblockAttemptCount'))
print('realSubmitblockSentCount=', meta.get('realSubmitblockSentCount'))
print('realSubmitblockErrorCount=', meta.get('realSubmitblockErrorCount'))
PY
```

Required preflight state:

- `templateModeEffective = daemon-template`
- `templateDaemonRpcReachable = true`
- `templateFetchStatus = ok`
- `realSubmitblockEnabled = false`
- ordinary accepted shares are still flowing

## Enable

Use a one-shot drill budget unless there is a strong reason not to.

Set the explicit flag and restart:

```bash
export PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true
export PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1
sudo systemctl restart pepepow-pool-stratum.service
```

If systemd uses an environment file or drop-in, apply the same variable there instead of only exporting it in a shell.

## Post-Restart Checks

Immediately verify the enabled state is unmistakable:

```bash
systemctl status pepepow-pool-stratum.service --no-pager --lines=25
tail -n 40 /home/ubuntu/pool-pepepow/.runtime/live-stratum/stratum.log
./ops/scripts/live-stratum.sh drill-status
curl -s http://127.0.0.1:8080/api/health | jq '.realSubmitblockEnabled, .realSubmitblockLastStatus, .realSubmitblockAttemptCount, .realSubmitblockSentCount, .realSubmitblockErrorCount'
```

Expected:

- startup log contains the warning:
  - `REAL submitblock ENABLED via PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true`
- `realSubmitblockEnabled = true`
- `realSubmitblockSendBudget = 1`
- `realSubmitblockSendBudgetRemaining = 1`
- no submit attempt occurs unless a share reaches `meetsBlockTarget = true`

## Observation Points

Watch these files and fields during the enable window:

- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/stratum.log`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/share-events.jsonl`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/candidate-events.jsonl`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/candidate-outcome-events.jsonl`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/candidate-followup-events.jsonl`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/activity-snapshot.json`
- `http://127.0.0.1:8080/api/health`

Important fields:

- `submitblockRealSubmitStatus`
- `submitblockAttempted`
- `submitblockSent`
- `submitblockDaemonResult`
- `submitblockException`
- `realSubmitblockSendBudget`
- `realSubmitblockSendBudgetRemaining`
- `realSubmitblockLastStatus`
- `realSubmitblockLastAttemptAt`
- `realSubmitblockLastError`

Recommended observation command during the drill:

```bash
watch -n 2 ./ops/scripts/live-stratum.sh drill-status
./ops/scripts/live-stratum.sh candidate-events 5
./ops/scripts/live-stratum.sh candidate-outcomes 5
./ops/scripts/live-stratum.sh candidate-followup 5
./ops/scripts/live-stratum.sh candidate-followup 5 --record
./ops/scripts/live-stratum.sh candidate-followup-events 5
```

`candidate-events.jsonl` is append-only evidence for `meetsBlockTarget` shares only. It records the prepared candidate block hash, candidate prep status, dry-run status, real-submit status, payload hash/bytes, daemon result, and exception text when present.

Each candidate evidence entry also carries default manual follow-up fields:

- `followupStatus`
- `followupCheckedAt`
- `followupObservedHeight`
- `followupObservedBlockHash`
- `followupNote`

These default to a not-checked state in the append-only evidence file. Manual follow-up does not implement block lifecycle tracking; it only checks whether the recorded candidate block hash currently appears on the local daemon chain view.

`candidate-followup-events.jsonl` is a second append-only evidence file. It records explicit manual follow-up outcomes only when the operator runs `candidate-followup --record`.

`candidate-outcome-events.jsonl` is the compact consolidated view. It stays append-only and records:

- `candidateBlockHash`
- `submitblockRealSubmitStatus`
- `followupStatus`
- `candidateOutcomeStatus`

`candidateOutcomeStatus` meanings:

- `submitted`: candidate evidence exists and no recorded chain follow-up outcome has been applied yet
- `chain-match-found`: a recorded follow-up found the candidate block hash on the local chain
- `chain-match-not-found`: a recorded follow-up did not find the candidate block hash on the local chain
- `check-error`: a recorded follow-up check failed

Manual follow-up meanings:

- `match-found`: the candidate block hash is currently visible from the local daemon and the observed height/hash are returned.
- `no-match-found`: the local daemon does not currently report that candidate block hash.
- `check-error`: the local follow-up check could not complete cleanly.

Recording manual follow-up:

- inspect without recording:
  - `./ops/scripts/live-stratum.sh candidate-followup 5`
- inspect and append recorded follow-up evidence:
  - `./ops/scripts/live-stratum.sh candidate-followup 5 --record`
- inspect the compact consolidated outcome view:
  - `./ops/scripts/live-stratum.sh candidate-outcomes 5`
- inspect recorded follow-up evidence:
  - `./ops/scripts/live-stratum.sh candidate-followup-events 5`

## Abort Conditions

Abort immediately if any of the following occurs:

- `templateModeEffective != daemon-template`
- `templateDaemonRpcReachable != true`
- `templateFetchStatus != ok`
- `realSubmitblockEnabled != true` after the enable restart
- `realSubmitblockSendBudgetRemaining` is not the intended drill value
- `realSubmitblockErrorCount > 0`
- `realSubmitblockLastStatus = submit-error`
- any unexpected submit attempt occurs outside the intended drill window

## Abort / Rollback

Disable immediately and restart:

```bash
export PEPEPOW_ENABLE_REAL_SUBMITBLOCK=false
export PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1
sudo systemctl restart pepepow-pool-stratum.service
```

Then confirm:

```bash
systemctl status pepepow-pool-stratum.service --no-pager --lines=20
./ops/scripts/live-stratum.sh drill-status
curl -s http://127.0.0.1:8080/api/health | jq '.realSubmitblockEnabled, .realSubmitblockLastStatus'
```

Expected rollback state:

- `realSubmitblockEnabled = false`
- startup warning no longer appears
- ordinary shares continue unchanged
- no new real submit attempts occur after the restart
