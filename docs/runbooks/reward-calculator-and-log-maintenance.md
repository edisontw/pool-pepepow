# Reward Calculator and Log Maintenance Runbook

## Scope

This runbook documents two small-host operational topics that repeatedly affect
pool support work:

1. How the public Mining Reward Calculator should estimate PEPEW rewards.
2. How runtime logs should be bounded so JSONL and journal logs do not fill the
   disk on a small Oracle Cloud instance.

The goal is to prevent repeated rediscovery of the same assumptions and to keep
future UI or ops patches aligned with the current pool policy.

---

## 1. Mining Reward Calculator Policy

### Current homepage formula

The homepage Mining Reward Calculator should display an orphan-adjusted
_theoretical_ estimate, not a guaranteed payout and not a recorded payment
amount.

Current intended formula:

```text
estimated_pepew_per_day =
  (miner_hashrate / network_hashrate)
  * (86400 / 20)
  * 6500
  * 0.95
  * 0.65
  * (1 - pool_fee_ratio)
  * 0.75
```

Where:

- `6500` is the current PEPEPOW block reward.
- `0.95` accounts for the 5% developer-fee remainder.
- `0.65` is the miner-share side of the pool reward split.
- `(1 - pool_fee_ratio)` applies the pool fee when available from
  `/api/pool/summary`.
- `0.75` is the approximate non-orphan rate. In other words, an orphan rate near
  25% means roughly 75% of found blocks are expected to survive.
- `86400 / 20` assumes a 20-second block interval.

### What not to do

Do not add an arbitrary observed-payment calibration such as:

```text
* 0.55
```

Observed payments can be lower or delayed for reasons that should not be hidden
inside the calculator:

- pool luck variance
- orphan rate changes
- network hashrate changes
- payout timing
- immature block delay
- accounting or attribution issues that need operator review

The calculator should remain transparent and explain its assumptions.

### UI wording

Use wording similar to:

```text
Orphan-adjusted theoretical estimate.
Uses current block reward 6500 × 95% developer-fee remainder × 65% miner share
× pool fee × 75% non-orphan rate. Actual recorded payments can still differ
because of pool luck, network hashrate changes, and payment timing.
```

Avoid wording that implies a pending balance, payable amount, or guaranteed
income.

### Files that can affect calculator output

Known frontend paths:

```text
apps/frontend/site/index.html
apps/frontend/site/assets/app.js
apps/frontend/site/assets/pool-leaderboards.js
```

Before changing the calculator, check whether more than one script is rendering
or overriding the same DOM ids:

```text
#calc-pepew-hour
#calc-pepew-day
#calc-pepew-week
#calc-usdt-day
#calc-usdt-week
.estimate-warning
```

If two scripts write the same ids, users may briefly see the right formula and
then see it overwritten by an older formula. Prefer one render owner where
practical.

### Minimum validation after calculator changes

Run a syntax check for frontend JavaScript:

```bash
find apps/frontend/site/assets -maxdepth 1 -name '*.js' -print -exec node --check {} \;
git diff --check
```

If `index.html` inline calculator code was changed, also manually inspect the
inline script around the calculator constants.

---

## 2. Log and Runtime File Maintenance

### Why this matters

The pool can generate a lot of operational data. On a small single-host Oracle
Cloud VM, unbounded JSONL or journal logs can fill the disk and destabilize the
pool, API, or daemon.

The project should keep log growth bounded by default.

### Runtime files to watch

Common runtime locations include:

```text
.runtime/live-stratum/*.jsonl
.runtime/live-stratum/*.json
/var/lib/pepepow-pool/share-events.jsonl
/var/lib/pepepow-pool/share-events.*.jsonl
```

Large or fast-growing files are usually:

```text
share-events.jsonl
payment-actions.jsonl
candidate / followup JSONL logs
service journals
```

### Safe inspection commands

Use bounded reads only:

```bash
tail -n 200 .runtime/live-stratum/payment-actions.jsonl
tail -n 2000 /var/lib/pepepow-pool/share-events.jsonl
rg "blocked_" .runtime/live-stratum/payment-actions.jsonl | tail -n 50
journalctl -u pepepow-pool-stratum.service -n 200 --no-pager
journalctl -u pepepow-pool-api.service -n 200 --no-pager
```

Avoid full-file reads or broad scans:

```bash
cat .runtime/live-stratum/*.jsonl
rg keyword .runtime/live-stratum/
pandas.read_json(...)
```

### Disk usage checks

Use these before deep debugging or after a noisy incident:

```bash
df -h
sudo du -h -d 1 /var/lib/pepepow-pool 2>/dev/null | sort -h
du -h -d 1 .runtime/live-stratum 2>/dev/null | sort -h
journalctl --disk-usage
```

### Stratum share-event rotation

The Stratum activity ingest path has environment knobs for JSONL rotation:

```text
PEPEPOW_POOL_CORE_ACTIVITY_LOG_ROTATE_BYTES
PEPEPOW_POOL_CORE_ACTIVITY_LOG_RETENTION_FILES
```

These should be set to bounded values in the Stratum environment file. The exact
numbers can be tuned, but the policy is:

- keep enough recent share data for restart recovery and debugging
- do not keep unlimited raw JSONL history on the small host
- rely on snapshots and summaries for frontend/API reads

Example conservative starting point:

```bash
PEPEPOW_POOL_CORE_ACTIVITY_LOG_ROTATE_BYTES=104857600
PEPEPOW_POOL_CORE_ACTIVITY_LOG_RETENTION_FILES=10
```

That keeps roughly 1 GB of rotated share JSONL history plus the active file.
Use a smaller value if the host has limited free disk.

### systemd journal cap

Use journald limits so service logs cannot consume the whole disk. Example
host-level policy:

```ini
# /etc/systemd/journald.conf.d/pepepow-pool.conf
[Journal]
SystemMaxUse=1G
SystemKeepFree=1G
MaxRetentionSec=14day
```

Apply with:

```bash
sudo systemctl restart systemd-journald
journalctl --disk-usage
```

Do not delete daemon chain data or wallet data to reclaim space.

### logrotate for file logs

If a component writes file logs outside journald, add a bounded logrotate rule.
Example pattern:

```text
/var/log/pepepow-pool/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
}
```

Prefer journald plus bounded runtime JSONL rotation where possible.

### API and frontend rule

The public API and frontend must not read raw JSONL files on request paths.
They should read summarized snapshots such as:

```text
activity-snapshot.json
pool-snapshot.json
payments-snapshot.json
accepted-candidates.json
```

This protects the 1-core host from expensive request-time parsing and prevents
large files from coupling directly to the public surface.

---

## 3. Incident checklist: disk almost full

Use this bounded sequence:

```bash
df -h
journalctl --disk-usage
sudo du -h -d 1 /var/lib/pepepow-pool 2>/dev/null | sort -h
du -h -d 1 .runtime/live-stratum 2>/dev/null | sort -h
systemctl status pepepow-pool-stratum.service --no-pager
systemctl status pepepow-pool-api.service --no-pager
```

Then decide:

1. If journald is large, reduce journald retention and vacuum old entries.
2. If Stratum share JSONL is large, verify rotation environment variables.
3. If rotated share logs are too many, reduce retention.
4. If unknown files dominate disk, inspect only bounded directory summaries.
5. Do not remove wallet, daemon chain, or payout records unless there is an
   explicit backup and operator approval.

Safe journal cleanup example:

```bash
sudo journalctl --vacuum-size=1G
```

Avoid broad deletion commands. Any cleanup command should name exact files or
retention policy and should preserve current snapshots and payment records.

---

## 4. Change discipline

When changing either calculator logic or log retention:

- keep the patch small
- update this runbook if the formula or retention policy changes
- run syntax checks for changed scripts
- do not change daemon RPC, wallet RPC, payout send, or submitblock flags
- do not introduce heavy services or databases for routine log handling
