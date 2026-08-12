# systemd

These unit files target the production Ubuntu deployment layouts used by PEPEPOW Pool. Existing Pool services may use the `/opt/pepepow-pool` layout; the Pure SOLO production units use `/home/ubuntu/pool-pepepow` and `/var/lib/pepepow-pool/solo`.

- `pepepow-pool-core.service` runs the runtime snapshot producer
- `pepepow-pool-stratum.service` runs the Pool Stratum ingress and activity snapshot writer
- `pepepow-pool-stratum-solo.service` runs the Pure SOLO Stratum ingress on port 39334
- `pepepow-pool-solo-lifecycle-refresh.service` refreshes only unresolved, actually-submitted SOLO block candidates and rebuilds `accepted-candidates.json`
- `pepepow-pool-solo-lifecycle-refresh.timer` runs the SOLO lifecycle refresh every minute so public API / Miner Lookup does not depend on the hourly payout cycle
- `pepepow-pool-api.service` serves the public API from runtime/fallback snapshots
- `pepepow-pool-frontend.service` serves the static frontend

The SOLO lifecycle refresher reads a bounded tail of candidate/outcome JSONL, skips candidates already confirmed by `match-found`, and uses the persistent SOLO environment file for daemon RPC credentials. It does not send payouts or call `submitblock`.
