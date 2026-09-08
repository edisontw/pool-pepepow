#!/usr/bin/env bash
set -e

echo "=== GIT STATUS & COMMIT ==="
git status --short
echo "HEAD: $(git rev-parse HEAD)"
git log -3 --oneline
echo "ORIGIN: $(git rev-parse origin/main)"

echo "=== SWAP & FSTAB ==="
swapon --show
free -h
grep -n '/swapfile' /etc/fstab || true

echo "=== LOGROTATE CHECK ==="
sudo logrotate -d /etc/logrotate.d/pepepow-pool-runtime 2>&1 | tail -n 15
sudo systemctl reset-failed logrotate.service || true
sudo systemctl is-failed logrotate.service || true

echo "=== PAYOUT PREFLIGHT & RECONCILIATION ==="
python3 -c '
import sys
sys.path.insert(0, "ops/scripts")
import payout_helper
actions_path = "/var/lib/pepepow-pool/payment-actions.jsonl"
unresolved = payout_helper.get_unresolved_payment_intents(actions_path)
print(f"unresolved_payment_intents: {len(unresolved)}")
for u in unresolved:
    print("  unresolved:", u)
reconciled, ambiguous = payout_helper.reconcile_unresolved_payment_intents(actions_path, dry_run=True)
print(f"reconciled_count: {len(reconciled)}")
print(f"ambiguous_count: {len(ambiguous)}")
'

echo "=== PRODUCTION SERVICES ==="
for unit in pepepowd.service pepepow-pool-stratum.service pepepow-pool-stratum-solo.service pepepow-pool-api.service pepepow-pool-auto-payout.timer; do
    echo "$unit: $(systemctl is-active $unit)"
done

echo "=== LISTENERS ==="
ss -lntp | grep -E '39333|39334|8080' || true

echo "=== DAEMON STATUS ==="
PEPEPOW-cli getblockchaininfo | grep -E 'blocks|headers|initialblockdownload'
PEPEPOW-cli getnetworkinfo | grep -E 'connections'

echo "=== API HEALTH & SNAPSHOTS ==="
curl -s http://127.0.0.1:8080/api/health
echo ""
curl -sk https://pool.pepepow.net/api/health
echo ""
curl -sk https://pool.pepepow.net/api/pool/summary | head -c 200
echo ""
curl -sk https://pool.pepepow.net/api/solo/summary | head -c 200
echo ""
curl -s -o /dev/null -w "payments.html status: %{http_code}\n" https://pool.pepepow.net/payments.html

echo "=== OOM & SYSTEM PRESSURE CHECK ==="
dmesg -T | grep -i -E 'oom|out of memory|killed process' | tail -n 10 || echo "No OOM events in dmesg since boot"
uptime
ps aux | grep -E 'PEPEPOWd|python' | grep -v grep | awk '{print $1, $2, $4, $5, $6, $11}'
df -h /
