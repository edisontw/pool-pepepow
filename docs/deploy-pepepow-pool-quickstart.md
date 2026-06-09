# Deploy PEPEPOW Pool Quickstart

This is an operator-facing quickstart for deploying and managing a PEPEPOW-only
community pool. It is written for a low-resource Oracle Cloud Ubuntu ARM64 host
using systemd and nginx.

## Target Host

- Oracle Cloud VM
- Ubuntu
- ARM64 / aarch64
- systemd
- nginx
- low resource host

## Components

- `PEPEPOWd`: PEPEPOW daemon; keep daemon RPC private.
- Stratum ingress: public miner-facing Stratum listener.
- `pool-core` snapshot producer: writes pool and network snapshots.
- API: read-only public HTTP API.
- Static frontend: public website that reads the API only.
- nginx: public HTTPS reverse proxy and static file server.

## Ports

Public:

- `80/tcp`: HTTP web
- `443/tcp`: HTTPS web/API
- `39333/tcp`: Stratum mining endpoint

Private-only:

- daemon RPC
- wallet RPC
- runtime files and snapshots
- payout/admin tooling

## Basic Install Flow

Clone the repository:

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/YOUR_ORG_OR_USER/pool-pepepow.git pepepow-pool
sudo chown -R "$USER":"$USER" /opt/pepepow-pool
cd /opt/pepepow-pool
```

Install OS and Python dependencies:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip nginx git curl jq
```

Install API Python dependencies:

```bash
cd /opt/pepepow-pool/apps/api
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
deactivate
cd /opt/pepepow-pool
```

Configure PEPEPOWd RPC on localhost only:

```ini
server=1
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcport=8834
rpcuser=change-me
rpcpassword=change-me
```

Restart `PEPEPOWd` after changing RPC settings. Do not expose the daemon RPC
port publicly.

Configure environment files:

```bash
cp ops/env/api.env.example ops/env/api.env 2>/dev/null || true
cp ops/env/pool-core.env.example ops/env/pool-core.env 2>/dev/null || true
editor ops/env/api.env
editor ops/env/pool-core.env
```

At minimum, align the pool-core env with the daemon RPC URL, user, password,
snapshot paths, Stratum bind host, and Stratum port `39333`.

Install systemd units:

```bash
sudo cp ops/systemd/pepepow-pool-core.service /etc/systemd/system/
sudo cp ops/systemd/pepepow-pool-stratum.service /etc/systemd/system/
sudo cp ops/systemd/pepepow-pool-api.service /etc/systemd/system/
sudo cp ops/systemd/pepepow-pool-frontend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pepepow-pool-core.service
sudo systemctl enable --now pepepow-pool-stratum.service
sudo systemctl enable --now pepepow-pool-api.service
sudo systemctl enable --now pepepow-pool-frontend.service
```

Configure nginx:

```bash
sudo cp ops/nginx/pepepow-pool.conf.example /etc/nginx/sites-available/pepepow-pool.conf
sudo ln -sf /etc/nginx/sites-available/pepepow-pool.conf /etc/nginx/sites-enabled/pepepow-pool.conf
sudo nginx -t
sudo systemctl reload nginx
```

Open public firewall and Oracle Cloud ingress for:

- `80/tcp`
- `443/tcp`
- `39333/tcp`

Do not open daemon RPC, wallet RPC, runtime file paths, or admin tooling.

## Minimum Smoke Test

Before opening the pool publicly, also run the
[prelaunch checklist](runbooks/prelaunch-checklist.md).

```bash
curl -fsS https://pool.pepepow.net/api/health | jq
curl -fsS https://pool.pepepow.net/api/pool/summary | jq
curl -fsS https://pool.pepepow.net/api/network/summary | jq
curl -fsS https://pool.pepepow.net/api/payments | jq
ss -ltnp | grep 39333
sudo nginx -t
```

For local API checks before DNS/HTTPS is ready:

```bash
curl -fsS http://127.0.0.1:8080/api/health | jq
curl -fsS http://127.0.0.1:8080/api/pool/summary | jq
```

## Daily Management Commands

Service status:

```bash
systemctl status pepepow-pool-core.service --no-pager
systemctl status pepepow-pool-stratum.service --no-pager
systemctl status pepepow-pool-api.service --no-pager
systemctl status pepepow-pool-frontend.service --no-pager
```

API health checks:

```bash
curl -fsS https://pool.pepepow.net/api/health | jq
curl -fsS https://pool.pepepow.net/api/stats | jq
curl -fsS https://pool.pepepow.net/api/status | jq
```

Pool operations checks:

```bash
./ops/scripts/healthcheck.sh
./ops/scripts/live-stratum.sh status
./ops/scripts/live-stratum.sh drill-status
ss -ltnp | grep 39333
```

Logs:

```bash
journalctl -u pepepow-pool-core.service -n 100 --no-pager
journalctl -u pepepow-pool-stratum.service -n 100 --no-pager
journalctl -u pepepow-pool-api.service -n 100 --no-pager
journalctl -u pepepow-pool-frontend.service -n 100 --no-pager
```

## Safe Update Flow

Pull changes:

```bash
cd /opt/pepepow-pool
git pull
```

Run focused tests before restarting services:

```bash
PYTHONPATH=apps/api:ops/scripts python3 -m unittest tests.test_api_endpoints
PYTHONPATH=ops/scripts python3 -m unittest tests.test_payout_accounting
bash -n ops/scripts/*.sh
git diff --check
```

Restart only what changed:

```bash
sudo systemctl restart pepepow-pool-api.service
sudo systemctl restart pepepow-pool-frontend.service
```

Restart Stratum only when Stratum, pool-core runtime, or Stratum env changed:

```bash
sudo systemctl restart pepepow-pool-stratum.service
./ops/scripts/live-stratum.sh status
```

Restart the snapshot producer only when producer, snapshot, or daemon-RPC config
changed:

```bash
sudo systemctl restart pepepow-pool-core.service
```

## Do Not Expose

Never expose these publicly:

- daemon RPC
- wallet RPC
- Redis, if it is ever added
- raw runtime JSONL
- runtime snapshots or private runtime directories
- payout controls
- submit controls
- admin commands

This project is PEPEPOW-only. It does not claim multi-coin support, exchange
payouts, public admin payout controls, or public automatic payout readiness.

Redis is not required for the current deployment model.
