# Pure SOLO Production Submit Runbook

## Purpose

Keep public Pure SOLO mining on `pool.pepepow.net:39334` in the intended production state across deploys and service restarts.

The public SOLO listener must never silently accept mining work while real `submitblock` is disabled. Historical dry-run benchmarks are not the production configuration source of truth.

## Production Invariants

Production SOLO must use:

```text
PEPEPOW_POOL_CORE_MINING_MODE=solo
PEPEPOW_POOL_CORE_STRATUM_BIND_PORT=39334
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1000
```

SOLO activity files must remain under an isolated `/solo/` runtime path.

The production environment file is:

```text
/home/ubuntu/pool-pepepow/ops/env/pool-stratum-solo.env
```

It is intentionally gitignored because a deployed env may contain private RPC configuration.

The systemd unit is:

```text
pepepow-pool-stratum-solo.service
```

Before starting Python, the unit runs the preflight through `/usr/bin/bash`:

```text
ops/scripts/check-solo-production-env.sh
```

The preflight fails startup if the SOLO mode, port, isolated runtime paths, real-submit flag, or bounded send ceiling are unsafe.

## Deploy / Repair

From the production checkout:

```bash
cd /home/ubuntu/pool-pepepow
git pull --ff-only
```

Create the persistent production env only if it does not already exist:

```bash
if [ ! -f ops/env/pool-stratum-solo.env ]; then
  cp ops/env/pool-stratum-solo.env.example ops/env/pool-stratum-solo.env
fi
chmod 600 ops/env/pool-stratum-solo.env
```

Preserve any existing private RPC values. Ensure these production values are present:

```text
PEPEPOW_POOL_CORE_MINING_MODE=solo
PEPEPOW_POOL_CORE_STRATUM_BIND_PORT=39334
PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH=/var/lib/pepepow-pool/solo/share-events.jsonl
PEPEPOW_POOL_CORE_ACTIVITY_SNAPSHOT_OUTPUT=/var/lib/pepepow-pool/solo/activity-snapshot.json
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1000
```

Run the non-secret preflight directly:

```bash
bash ops/scripts/check-solo-production-env.sh ops/env/pool-stratum-solo.env
```

Expected result:

```text
solo-production-env: ok (submit enabled, max_sends=1000)
```

Install the current unit and restart SOLO only:

```bash
sudo cp ops/systemd/pepepow-pool-stratum-solo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart pepepow-pool-stratum-solo.service
```

## Smoke Test

```bash
systemctl status pepepow-pool-stratum-solo.service --no-pager
curl -s http://127.0.0.1:8080/api/solo/summary | jq
```

Inspect the activity snapshot without printing secrets:

```bash
python3 - <<'PY'
import json
p = "/var/lib/pepepow-pool/solo/activity-snapshot.json"
with open(p) as f:
    m = json.load(f).get("meta", {})
for k in (
    "realSubmitblockEnabled",
    "realSubmitblockSendBudget",
    "realSubmitblockSendBudgetRemaining",
    "realSubmitblockAttemptCount",
    "realSubmitblockSentCount",
    "realSubmitblockErrorCount",
    "realSubmitblockLastStatus",
    "realSubmitblockLastAttemptAt",
    "realSubmitblockLastError",
):
    print(f"{k}: {m.get(k)}")
PY
```

Immediately after restart, the critical expected state is:

```text
realSubmitblockEnabled: True
realSubmitblockSendBudgetRemaining: > 0
```

Attempt/sent counters may remain zero until the next natural block-target share.

## Failure Signature

This is a production fault:

```text
meetsBlockTarget: true
candidatePrepStatus: candidate-prepared-complete
submitblockRealSubmitStatus: submit-disabled-flag-off
submitblockAttempted: false
submitblockSent: false
```

If this appears, repair the persistent SOLO env and restart the SOLO service. Do not continue mining indefinitely in this state.

## Historical Candidates

Do not manually replay old candidates that were found while real submit was disabled. Their previous-block anchors are stale and they are audit evidence only.

Only future candidates produced from current daemon-template jobs should enter the normal production submit path.

## Safety Boundaries

Keep these guards enabled:

- block-target validation
- current/fresh previous-block validation
- bounded `PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS`
- daemon result recording
- candidate lifecycle tracking
- Pool/SOLO runtime and accounting isolation

Do not expose daemon RPC, submit controls, or runtime files publicly.
