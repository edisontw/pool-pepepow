# PEPEPOW Pool Systemd Examples

These are examples for operators. Do not install or enable them without an explicit maintenance decision.

## Wallet Watchdog Service

Example `/etc/systemd/system/pepepow-pool-wallet-watchdog.service`:

```ini
[Unit]
Description=PEPEPOW pool wallet watchdog
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/pool-pepepow
ExecStart=/home/ubuntu/pool-pepepow/ops/scripts/live-stratum.sh pool-wallet-watchdog --format human
```

## Wallet Watchdog Timer

Example `/etc/systemd/system/pepepow-pool-wallet-watchdog.timer`:

```ini
[Unit]
Description=Run PEPEPOW pool wallet watchdog every 15 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
AccuracySec=30s
Persistent=true
Unit=pepepow-pool-wallet-watchdog.service

[Install]
WantedBy=timers.target
```

Useful read-only checks after installation:

```bash
systemctl cat pepepow-pool-wallet-watchdog.service
systemctl cat pepepow-pool-wallet-watchdog.timer
systemctl list-timers pepepow-pool-wallet-watchdog.timer --no-pager
```

## Payout Timer Guard Notes

Any auto payout service or timer should keep real wallet sends guarded by explicit environment and low send limits:

```ini
Environment=PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true
Environment=PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS=1
Environment=PEPEPOW_AUTO_PAYOUT_MAX_SENDS=1
Environment=PEPEPOW_MIN_PAYOUT=1000
Environment=PEPEPOW_POOL_FEE_PERCENT=1.0
```

Do not keep broad rescue flags or operator backfill flags enabled in a normal timer.

Before enabling any payout timer, manually verify:

```bash
./ops/scripts/live-stratum.sh payout-candidates
./ops/scripts/live-stratum.sh payout-review
./ops/scripts/live-stratum.sh payout-wallet-dry-run
./ops/scripts/live-stratum.sh pool-wallet-watchdog --format human
```

After a timer payout, verify:

```bash
./ops/scripts/live-stratum.sh refresh-payment-confirmations
./ops/scripts/live-stratum.sh payment-audit --format human
./ops/scripts/live-stratum.sh pool-wallet-watchdog --format human
curl -s http://127.0.0.1:8080/api/payments | jq
```

