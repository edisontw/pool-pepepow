# Stratum Ingress Stress Results

Date: 2026-04-13

Setup:

- `apps/pool-core/stratum_ingress.py`
- `apps/api/app.py` on fallback base snapshot plus live activity snapshot overlay
- share generator: `apps/pool-core/tools/generate_shares.py`
- daemon intentionally not used

Command pattern:

```bash
python3 apps/pool-core/tools/generate_shares.py \
  --host 127.0.0.1 \
  --port 39333 \
  --rate <100|500|1000> \
  --duration 60 \
  --connections <10|25|50> \
  --workers-per-wallet 5 \
  --activity-log-path /tmp/pepepow-stress-run/share-events.jsonl \
  --activity-snapshot-path /tmp/pepepow-stress-run/activity-snapshot.json \
  --api-base-url http://127.0.0.1:18080/api \
  --pid <stratum-pid>
```

## Results

| Target shares/s | Connections | Shares sent | JSONL lines | Observed shares/s | CPU avg % | CPU max % | RSS avg MB | RSS max MB | API median ms | API p95 ms | Snapshot writes | Max snapshot lag s | Max sequence backlog |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 10 | 6000 | 6000 | 100.00 | 2.83 | 4.00 | 20.89 | 21.38 | 2.11 | 5.27 | 59 | 1.62 | 90 |
| 500 | 25 | 29991 | 29991 | 499.85 | 8.36 | 10.98 | 24.83 | 27.00 | 2.37 | 7.60 | 60 | 7.73 | 0 |
| 1000 | 50 | 59900 | 59900 | 998.33 | 16.36 | 18.98 | 33.14 | 37.38 | 2.62 | 9.27 | 58 | 10.36 | 0 |

## Notes

- All three runs completed without crashes.
- `responsesOk == sharesSent` for every tier.
- API stayed on `200` responses throughout sampling.
- `/api/pool/summary` reflected live share-derived miner activity during and after load.
- Snapshot lag stayed bounded but rose at higher rates because snapshot generation is deliberately rate-limited to once per second and writes full JSON snapshots.
- These measurements predate the current synthetic job mode update.
- The current implementation now pushes synthetic/fake `mining.set_difficulty` and `mining.notify`, but still does not perform real template retrieval or real share validation.
