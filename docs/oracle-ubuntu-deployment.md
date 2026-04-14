# Oracle Ubuntu Deployment

## Target

- Oracle Cloud VM
- Ubuntu 22.04
- ARM64 / aarch64
- systemd
- nginx

## Public Services

- website via nginx
- public API via nginx
- public Stratum port

## Private Services

- PEPEPOWd RPC
- internal snapshot files
- future payout tooling
- optional future Redis

Keep private services bound to `127.0.0.1` or a private subnet only.

## Suggested Paths

- code: `/opt/pepepow-pool`
- runtime snapshot: `/var/lib/pepepow-pool/pool-snapshot.json`
- activity snapshot: `/var/lib/pepepow-pool/activity-snapshot.json`
- share log: `/var/lib/pepepow-pool/share-events.jsonl`
- env files: `/opt/pepepow-pool/ops/env`

## Bootstrap

```bash
cd /opt/pepepow-pool
./ops/scripts/bootstrap.sh
```

Review and edit:

- `ops/env/api.env`
- `ops/env/frontend.env`
- `ops/env/pool-core.env`

## Enable RPC In PEPEPOWd

Edit `~/.PEPEPOWcore/PEPEPOW.conf` for the daemon user:

```ini
server=1
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcport=8834
rpcuser=change-me
rpcpassword=change-me
```

The exact RPC port is whatever you configure in `PEPEPOW.conf`. Keep
`ops/env/pool-core.env` aligned with it. Keep RPC bound to localhost only. Do
not expose port `8834` publicly.

After editing the config:

```bash
mkdir -p ~/.PEPEPOWcore/backups
cp ~/.PEPEPOWcore/PEPEPOW.conf \
  ~/.PEPEPOWcore/backups/PEPEPOW.conf.$(date -u +%Y%m%dT%H%M%SZ)
pkill PEPEPOWd
./PEPEPOWd -daemon
```

Use stop then start if daemon is managed by systemd. Do not rely on reload.

## systemd Units

```bash
cp ops/systemd/pepepow-pool-api.service /etc/systemd/system/
cp ops/systemd/pepepow-pool-frontend.service /etc/systemd/system/
cp ops/systemd/pepepow-pool-core.service /etc/systemd/system/
cp ops/systemd/pepepow-pool-stratum.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now pepepow-pool-stratum.service
systemctl enable --now pepepow-pool-api.service
systemctl enable --now pepepow-pool-frontend.service
```

Optional chain snapshot producer:

```bash
systemctl enable --now pepepow-pool-core.service
```

## nginx

```bash
cp ops/nginx/pepepow-pool.conf.example /etc/nginx/sites-available/pepepow-pool.conf
ln -s /etc/nginx/sites-available/pepepow-pool.conf /etc/nginx/sites-enabled/pepepow-pool.conf
nginx -t
systemctl reload nginx
```

## Public Stratum Exposure Checklist

For public synthetic Stratum preflight or later public Stratum rollout, verify
all of the following:

- the process is listening on the intended port, for example `39333/tcp`
- OCI VCN ingress allows the port
- OCI Security List or NSG allows the port
- host firewall allows the port
- daemon RPC stays private on `127.0.0.1:8834`

Recommended checks:

```bash
ss -ltnp | grep 39333
sudo iptables -S
sudo nft list ruleset
nc -vz 127.0.0.1 39333
```

From an external host:

```bash
nc -vz <public-ip> 39333
```

## OCI And Host Firewall Notes

OCI ingress rules alone are not sufficient proof that an external miner can
reach the pool.

Important notes:

- host firewall must also allow the synthetic Stratum port, such as
  `39333/tcp`
- Oracle-provided Ubuntu images may ship with default `iptables` rules
- this failure mode is an ops exposure problem, not a Stratum protocol problem
- if the port is reachable locally but not externally, inspect host firewall
  before assuming a miner compatibility issue

Keep this split explicit:

- OCI handles network-level ingress exposure
- host firewall still decides whether packets reach the listening process

## Troubleshooting External Reachability

If a real external miner cannot connect:

1. Confirm the service is listening with `ss -ltnp | grep 39333`.
2. Confirm the port is reachable locally with `nc -vz 127.0.0.1 39333`.
3. Confirm OCI ingress includes `39333/tcp`.
4. Inspect host filtering with `sudo iptables -S` and `sudo nft list ruleset`.
5. Retry from an external host with `nc -vz <public-ip> 39333`.

If OCI ingress is already open but external access still fails, inspect host
firewall first. Do not treat that symptom as miner protocol mismatch until the
host exposure path is confirmed.

## Verification

```bash
./ops/scripts/healthcheck.sh
curl http://127.0.0.1:8080/api/pool/summary
curl http://127.0.0.1:8080/api/network/summary
curl http://127.0.0.1:8080/api/blocks
curl http://127.0.0.1:8080/api/health
```

Healthy current runtime mode should show:

- `snapshotSource = runtime` or `fallback`
- activity overlay fields present when Stratum ingest is live
- `activityMode = stratum-share-ingest`
- `activityDerivedFromShares = true`
- `blockchainVerified = false`

If the daemon is still reindexing, current runtime mode may still be valid
while:

- `chainState = reindexing` or `syncing`
- `network.synced = false`
- chain values remain non-final
- share-derived activity data can still be live

## Submit-Test Verification

Use a low-rate local test:

```bash
cd /opt/pepepow-pool
python3 apps/pool-core/tools/generate_shares.py \
  --host 127.0.0.1 \
  --port 3333 \
  --rate 1 \
  --duration 3 \
  --connections 1 \
  --activity-log-path /var/lib/pepepow-pool/share-events.jsonl \
  --activity-snapshot-path /var/lib/pepepow-pool/activity-snapshot.json \
  --api-base-url http://127.0.0.1:8080/api
```

Then verify:

- `tail -n 3 /var/lib/pepepow-pool/share-events.jsonl`
- `curl http://127.0.0.1:8080/api/pool/summary`
- `curl http://127.0.0.1:8080/api/miner/YOUR_WALLET`

## Failure Mode

If daemon RPC is unavailable:

- producer keeps the previous runtime snapshot file if one exists
- API serves stale runtime snapshot if it exists
- otherwise API falls back to repository mock snapshot
- health output shows degraded chain status
- Stratum ingress can still accept shares and update the activity snapshot

## Local Activity Accounting Mode

The current mode is daemon-independent Stratum share ingest backed by a local
JSONL event log.

Recommended paths:

- `/var/lib/pepepow-pool/share-events.jsonl`
- `/var/lib/pepepow-pool/activity-snapshot.json`

This data affects:

- `pool.activeMiners`
- `pool.activeWorkers`
- `pool.poolHashrate`
- `pool.workerDistribution`
- `/api/miner/<wallet>`

It does not replace chain data ownership and is not blockchain verified.

## Benchmarks

Reference stress results:

- [2026-04-13-stratum-ingress.md](/home/ubuntu/pool-pepepow/docs/benchmarks/2026-04-13-stratum-ingress.md)
- [2026-04-14-external-gpu-stratum-smoke.md](/home/ubuntu/pool-pepepow/docs/benchmarks/2026-04-14-external-gpu-stratum-smoke.md)
