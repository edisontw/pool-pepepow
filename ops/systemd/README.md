# systemd

These unit files target the production Ubuntu deployment under `/home/ubuntu/pool-pepepow`. Pool Stratum observations and rounds snapshots use `/home/ubuntu/pool-pepepow/.runtime/live-stratum`; the frozen Pool attribution ledger is stored at `/var/lib/pepepow-pool/round-attribution.jsonl`.

- `pepepow-pool-core.service` runs the runtime snapshot producer
- `pepepow-pool-stratum.service` runs the Pool Stratum ingress and activity snapshot writer
- `pepepow-pool-stratum-solo.service` runs the Pure SOLO Stratum ingress on port 39334
- `pepepow-pool-solo-lifecycle-refresh.service` refreshes unresolved, actually-submitted SOLO block candidates, rebuilds canonical `accepted-candidates.json`, and then builds read-only merged SOLO public snapshots
- `pepepow-pool-solo-lifecycle-refresh.timer` runs the SOLO lifecycle/public snapshot refresh every minute so Miner Lookup does not depend on the hourly payout cycle
- `pepepow-pool-api.service` serves the public API using persistent `ops/env/api.env`
- `pepepow-pool-frontend.service` serves the static frontend
- `pepepow-pool-auto-payout.service.d/solo-canonical.conf` appends the guarded canonical SOLO payout after the existing hourly Pool payout without changing the Pool runtime
- `pepepow-pool-auto-payout.timer` is the sole automated payout scheduler; do not also schedule `auto-payout-once` from cron
- `pepepow-pool-rounds-refresh.timer` refreshes Pool round snapshots every five minutes

The canonical SOLO runtime remains `/var/lib/pepepow-pool/solo` and is the only SOLO source used by lifecycle/payout/accounting. The API-only merged block/payment history is written under `/var/lib/pepepow-pool/solo-public`; this preserves legacy display history without adding old records back into payout inputs or replay guards.

The hourly Pool payout keeps its existing runtime. The SOLO payout drop-in runs the existing `solo-auto-payout-once` command with `PEPEPOW_LIVE_STRATUM_RUNTIME_DIR=/var/lib/pepepow-pool`, so its isolated payout files are written under `/var/lib/pepepow-pool/solo`. It inherits the parent service's guarded wallet-payout enablement but uses its own bounded `PEPEPOW_SOLO_AUTO_PAYOUT_MAX_SENDS=10` ceiling.

The Pool workflow holds a non-blocking `/run/lock/pepepow-pool-auto-payout.lock` before candidate refresh, round accounting, and wallet payout stages. A concurrent invocation exits safely without attempting a payout.

The SOLO lifecycle refresher reads a bounded tail of candidate/outcome JSONL, skips candidates already confirmed by `match-found`, and uses the persistent SOLO environment file for daemon RPC credentials. It does not send payouts or call `submitblock`.

The Pool rounds refresher appends validated Pool wallet weights to the path in `PEPEPOW_ROUND_ATTRIBUTION_LEDGER`, defaulting to `${RUNTIME_DIR}/round-attribution.jsonl`. Its production drop-in sets the canonical file to `/var/lib/pepepow-pool/round-attribution.jsonl`, while accepted candidates, share events, activity data, and rounds snapshots remain in the production Stratum runtime. Raw share logs are the short-term reconstruction source; the attribution ledger is the durable accounting source used to rebuild `rounds-snapshot.json` after those logs rotate or are pruned. Payment action records remain the separate authority for payout replay and payment history. The repo-local `.runtime/live-stratum/round-attribution.jsonl` is legacy, non-authoritative data; keep it intact.

```sh
PEPEPOW_LIVE_STRATUM_RUNTIME_DIR=/home/ubuntu/pool-pepepow/.runtime/live-stratum \
PEPEPOW_ROUND_ATTRIBUTION_LEDGER=/var/lib/pepepow-pool/round-attribution.jsonl \
  /home/ubuntu/pool-pepepow/ops/scripts/live-stratum.sh track-rounds
```

Confirmed Pool candidates blocked with `missing_share_data` have historical attribution unavailable; keep them blocked and outside normal unpaid-ready reporting unless a valid frozen attribution record exists. Do not infer wallet weights or treat their aggregate reward as payable.
