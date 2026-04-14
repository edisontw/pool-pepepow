# 2026-04-14 Live Synthetic External Miner Baseline

## Endpoint

- `stratum+tcp://192.9.160.179:39333`

## Known-Good External Miner Command

```bash
./hoo_gpu -o stratum+tcp://192.9.160.179:39333 -u PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD -gpu-id 0 -p x --pepepow
```

## Effective Difficulty

- `0.00000001`

## Exact Difficulty Source

- file: `/home/ubuntu/pool-pepepow/.runtime/live-stratum/launch.env`
- variable: `PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY`

Current known-good value:

```bash
PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY=0.00000001
```

## Wrapper Commands

Start:

```bash
/home/ubuntu/pool-pepepow/ops/scripts/live-stratum.sh start
```

Status:

```bash
/home/ubuntu/pool-pepepow/ops/scripts/live-stratum.sh status
```

Restart:

```bash
/home/ubuntu/pool-pepepow/ops/scripts/live-stratum.sh restart
```

Logs:

```bash
/home/ubuntu/pool-pepepow/ops/scripts/live-stratum.sh logs
```

## Runtime File Paths

- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/stratum.pid`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/stratum.log`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/share-events.jsonl`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/activity-snapshot.json`
- `/home/ubuntu/pool-pepepow/.runtime/live-stratum/launch.env`

## Observed Result Summary

- continuous accepted shares
- restart recovery works
- `shareCount` continues accumulating

## Current Boundaries

- synthetic only
- daemon-independent
- non-validated
- no `submitblock`
- no payout
