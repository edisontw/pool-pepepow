# systemd

These unit files target the current production Ubuntu deployment layout under `/home/ubuntu/pool-pepepow`, with runtime snapshots under `/var/lib/pepepow-pool`.

- `pepepow-pool-core.service` runs the runtime snapshot producer
- `pepepow-pool-stratum.service` runs the Pool Stratum ingress and activity snapshot writer
- `pepepow-pool-stratum-solo.service` runs the Pure SOLO Stratum ingress on port 39334
- `pepepow-pool-solo-lifecycle-refresh.service` refreshes unresolved, actually-submitted SOLO block candidates, rebuilds canonical `accepted-candidates.json`, and then builds read-only merged SOLO public snapshots
- `pepepow-pool-solo-lifecycle-refresh.timer` runs the SOLO lifecycle/public snapshot refresh every minute so Miner Lookup does not depend on the hourly payout cycle
- `pepepow-pool-api.service` serves the public API using persistent `ops/env/api.env`
- `pepepow-pool-frontend.service` serves the static frontend

The canonical SOLO runtime remains `/var/lib/pepepow-pool/solo` and is the only SOLO source used by lifecycle/payout/accounting. The API-only merged block/payment history is written under `/var/lib/pepepow-pool/solo-public`; this preserves legacy display history without adding old records back into payout inputs or replay guards.

The SOLO lifecycle refresher reads a bounded tail of candidate/outcome JSONL, skips candidates already confirmed by `match-found`, and uses the persistent SOLO environment file for daemon RPC credentials. It does not send payouts or call `submitblock`.
