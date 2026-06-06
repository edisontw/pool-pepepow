# scripts

This directory contains small operational scripts used during deployment,
maintenance, and verification.

- `healthcheck.sh` checks the public API and prints runtime/fallback, chain, and
  activity metadata
- `live-stratum.sh` manages the repo-local synthetic Stratum live-test listener
  with fixed PID/log/snapshot paths under `.runtime/live-stratum`
- `restart-services.sh` restarts the pool core, API, and frontend services
- `run-stratum-preflight.sh` starts the daemon-independent synthetic Stratum
  preflight listener and writes pool-side artifacts under
  `/tmp/pepepow-preflight` by default
- `stratum_smoke_report.py` summarizes retained synthetic Stratum smoke
  artifacts into the standard report format

## `run-stratum-preflight.sh`

Purpose:

- launch an isolated synthetic Stratum endpoint without daemon/template
  dependencies
- expose a foreground debugging target for local or external miner smoke tests
- emit `stratum.log`, `share-events.jsonl`, and `activity-snapshot.json`
- stay separate from the repo-local live-test wrapper used for repeated retests

Important environment variables:

- `PEPEPOW_PREFLIGHT_PUBLIC_HOST`
- `PEPEPOW_PREFLIGHT_PORT`
- `PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY`
- `PEPEPOW_PREFLIGHT_JOB_INTERVAL_SECONDS`
- `PEPEPOW_PREFLIGHT_OUTPUT_DIR`

External GPU smoke example:

```bash
PEPEPOW_PREFLIGHT_PUBLIC_HOST=pool.pepepow.net \
PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY=0.000001 \
/home/ubuntu/pool-pepepow/ops/scripts/run-stratum-preflight.sh
```

## `live-stratum.sh`

Purpose:

- provide a stable synthetic Stratum endpoint for repeated external miner retests
- keep PID, stdout log, share log, and activity snapshot paths fixed
- make the effective synthetic difficulty explicit via `launch.env` and `status`
- support fast `start`, `stop`, `restart`, `status`, `logs`, and `paths` flows
- rotate `stratum.log` on start when it grows beyond the configured size guard
- audit candidate probability from a bounded tail of `share-events.jsonl` with
  `candidate-probability-audit [tail-lines]`
- find one candidate’s bounded submit evidence from `submit-evidence.jsonl`
  with `submit-evidence-find <candidate_hash> [tail_lines]` (default tail
  window: `5000`)
- summarize recent candidate freshness and stale-prevblk / chain follow-up
  signals from bounded tails with `candidate-freshness-audit [tail_lines]`
  (default tail window: `200`)

Runtime paths:

- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/stratum.pid`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/stratum.log`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/share-events.jsonl`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/submit-evidence.jsonl`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/activity-snapshot.json`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/launch.env`

Operator note:

- managed production `live-stratum.sh` owns `.runtime/live-stratum/launch.env`,
  `.runtime/live-stratum/share-events.jsonl`,
  `.runtime/live-stratum/submit-evidence.jsonl`, and the public bind
  `0.0.0.0:39333`
- temporary parity, trace, or reference-miner harnesses must use a separate
  runtime root such as `/tmp/pepepow-parity-runtime`,
  `/tmp/pepepow-trace-runtime`, or
  `/home/ubuntu/.tmp/pepepow-parity-runtime`
- do not point temporary localhost harnesses at `.runtime/live-stratum`

Temporary parity harness example:

```bash
PARITY_RUNTIME_ROOT=/tmp/pepepow-parity-runtime
mkdir -p "${PARITY_RUNTIME_ROOT}"
export PARITY_RUNTIME_ROOT
# Keep .runtime/live-stratum reserved for managed production live-stratum.sh.
python3 - <<'PY'
from pathlib import Path
runtime = Path(__import__("os").environ["PARITY_RUNTIME_ROOT"])
print(f"using temporary runtime root: {runtime}")
PY
```

Example:

```bash
/home/ubuntu/pool-pepepow/ops/scripts/live-stratum.sh start
```

Effective difficulty:

- source of truth: `.runtime/live-stratum/launch.env`
- variable: `PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY`
- default live-test value: `0.00000001`
- override: export `PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY=<value>` before `start`
- estimation-only override: export `PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY=<value>` before `start`

Long-run note:

- `stratum.log` is rotated to `stratum.log.1` on `start` when it exceeds
  `PEPEPOW_LIVE_STRATUM_LOG_ROTATE_BYTES` (default `33554432`)

Candidate follow-up helper ordering:

- `candidate-followup --record` is the write step; it appends follow-up records
  to the append-only candidate follow-up and outcome logs
- `candidate-outcomes` and `candidate-followup-events` are read views over those
  append-only logs
- run `candidate-followup --record` to completion before reading
  `candidate-outcomes` or `candidate-followup-events`
- running these helpers concurrently can show temporary stale or incomplete
  views while the write step is still appending records
- this does not imply candidate prep, dry-run follow-up, or submitblock failure

## `stratum_smoke_report.py`

Purpose:

- read existing smoke artifacts instead of re-running the test
- produce a standard summary for compatibility/smoke evidence
- keep synthetic scope explicit in the final report

Important reminder:

- accepted shares in this report may still be synthetic only
- the report does not imply real share validation
- the report does not imply blockchain verification

External GPU smoke example:

```bash
python3 /home/ubuntu/pool-pepepow/ops/scripts/stratum_smoke_report.py \
  --share-log /tmp/pepepow-preflight/share-events.jsonl \
  --activity-snapshot /tmp/pepepow-preflight/activity-snapshot.json \
  --pool-log /tmp/pepepow-preflight/stratum.log \
  --miner-name 'HTN GPU Miner' \
  --miner-version 'hoo_gpu 1.4.7' \
  --source-provenance 'https://pepepow.org/mining/ ; https://htn.foztor.net/hoo_gpu.tar.gz' \
  --build-method 'wget -c https://htn.foztor.net/hoo_gpu.tar.gz -O - | tar -xz' \
  --environment-platform 'x86_64 Ubuntu + NVIDIA GPU' \
  --pool-command 'PEPEPOW_PREFLIGHT_PUBLIC_HOST=pool.pepepow.net PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY=0.000001 /home/ubuntu/pool-pepepow/ops/scripts/run-stratum-preflight.sh' \
  --miner-command './hoo_gpu -o stratum+tcp://pool.pepepow.net:39333 -u PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD -gpu-id 0 -p x --pepepow'
```
