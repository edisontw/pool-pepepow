# scripts

This directory contains small operational scripts used during deployment,
maintenance, and verification.

- `healthcheck.sh` checks the public API and prints runtime/fallback, chain, and
  activity metadata
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
- expose a reproducible target for local or external miner smoke tests
- emit `stratum.log`, `share-events.jsonl`, `activity-snapshot.json`, and
  `pool-snapshot.json`

Important environment variables:

- `PEPEPOW_PREFLIGHT_PUBLIC_HOST`
- `PEPEPOW_PREFLIGHT_PORT`
- `PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY`
- `PEPEPOW_PREFLIGHT_JOB_INTERVAL_SECONDS`
- `PEPEPOW_PREFLIGHT_OUTPUT_DIR`

External GPU smoke example:

```bash
PEPEPOW_PREFLIGHT_PUBLIC_HOST=192.9.160.179 \
PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY=0.000001 \
/home/ubuntu/pool-pepepow/ops/scripts/run-stratum-preflight.sh
```

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
  --pool-command 'PEPEPOW_PREFLIGHT_PUBLIC_HOST=192.9.160.179 PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY=0.000001 /home/ubuntu/pool-pepepow/ops/scripts/run-stratum-preflight.sh' \
  --miner-command './hoo_gpu -o stratum+tcp://192.9.160.179:39333 -u PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD -gpu-id 0 -p x --pepepow'
```
