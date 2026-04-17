# 2026-04-17 Systemd Daemon-Template Live Validation Baseline

## Scope

This artifact records one short live validation smoke on the current
systemd-managed daemon-template Stratum path.

It verifies live accepted-share continuity and status/counter alignment only.
It does not make this a full validating pool.

## Environment

- daemon: `PEPEPOWd v2.9.0.4-c1394e6`
- stratum service: `pepepow-pool-stratum.service`
- stratum mode: `daemon-template`
- endpoint: `stratum+tcp://192.9.160.179:39333`
- observed miner remote: `36.227.104.10:50238`

## Live Accepted Share Evidence

Observed from:

- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/share-events.jsonl`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/stratum.log`

Observed facts:

- fresh accepted shares were present at `2026-04-17T10:40:17Z`
- `jobSource = "daemon-template"`
- `jobStatus` continued across `current` and short `previous`
- `shareHashValidationMode = "hoohashv110-pepew-header80"`
- `shareHashValidationStatus = "share-hash-invalid"`
- `targetValidationStatus = "candidate-possible"`
- `accepted_shares_total = 85482`
- `active_miners = 1`

Representative accepted submit:

- `jobId = "job-0000000000000097"`
- `jobSource = "daemon-template"`
- `remoteAddress = "36.227.104.10:50238"`
- `timestamp = "2026-04-17T10:40:17Z"`

## Snapshot / API Alignment

Observed alignment between:

- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/activity-snapshot.json`
- `http://127.0.0.1:8080/api/health`

Aligned values:

- `templateModeEffective = "daemon-template"`
- `templateDaemonRpcStatus = "reachable"`
- `templateFetchStatus = "ok"`
- `shareHashValidationMode = "hoohashv110-pepew-header80"`
- `submitAcceptedCount = 3086`
- `submitRejectedCount = 0`
- `submitShareHashValidationCounts.share-hash-invalid = 3086`
- `submitShareHashValidationCounts.share-hash-valid = 0`
- `submitTargetValidationCounts.candidate-possible = 3086`

## Known Limitations

- `share-hash-invalid` remains the observed live result
- local share-hash handling is still classification-only
- `placeholderPayout = true` remains present in daemon-template preimage context
- this baseline does not imply safe accept/reject gating
- this baseline does not imply `submitblock` safety
