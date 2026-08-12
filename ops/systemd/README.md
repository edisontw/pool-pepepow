# systemd

These unit files target the current production Ubuntu deployment layout under `/home/ubuntu/pool-pepepow`, with runtime snapshots under `/var/lib/pepepow-pool`.

- `pepepow-pool-core.service` runs the runtime snapshot producer
- `pepepow-pool-stratum.service` runs the Pool Stratum ingress and activity snapshot writer
- `pepepow-pool-stratum-solo.service` runs the Pure SOLO Stratum ingress on port 39334
- `pepepow-pool-solo-lifecycle-refresh.service` refreshes unresolved, actually-submitted SOLO block candidates, rebuilds canonical `accepted-candidates.json`, and then builds read-only merged SOLO public snapshots
- `pepepow-pool-solo-lifecycle-refresh.timer` runs the SOLO lifecycle/public snapshot refresh every minute so Miner Lookup does not depend on the hourly payout cycle
- `pepepow-pool-api.service` serves the public API using persistent `ops/env/api.env`
- `pepepow-pool-frontend.service` serves the static frontend
- `pepepow-pool-auto-payout.service.d/solo-canonical.conf` appends the guarded canonical SOLO payout after the existing hourly Pool payout without changing the Pool runtime

The canonical SOLO runtime remains `/var/lib/pepepow-pool/solo` and is the only SOLO source used by lifecycle/payout/accounting. The API-only merged block/payment history is written under `/var/lib/pepepow-pool/solo-public`; this preserves legacy display history without adding old records back into payout inputs or replay guards.

The hourly Pool payout keeps its existing runtime. The SOLO payout drop-in runs the existing `solo-auto-payout-once` command with `PEPEPOW_LIVE_STRATUM_RUNTIME_DIR=/var/lib/pepepow-pool`, so its isolated payout files are written under `/var/lib/pepepow-pool/solo`. It inherits the parent service's guarded wallet-payout enablement but uses its own bounded `PEPEPOW_SOLO_AUTO_PAYOUT_MAX_SENDS=10` ceiling.

The SOLO lifecycle refresher reads a bounded tail of candidate/outcome JSONL, skips candidates already confirmed by `match-found`, and uses the persistent SOLO environment file for daemon RPC credentials. It does not send payouts or call `submitblock`.
