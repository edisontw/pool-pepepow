# PEPEPOW Pool Prelaunch Checklist

Use this before a public launch, relaunch, DNS change, or major deployment
cleanup. It is a verification checklist only. Do not restart services or change
runtime paths just because this document mentions them.

## A. Git / Repo Cleanup

Checklist:

- `git status --short` is clean before release or only expected files are dirty.
- `git diff --check` passes.
- No secrets are committed.
- No runtime JSONL files are committed.
- No `.env` files with real passwords are committed.
- Favicon and static assets are present if the public site expects them.
- Shell scripts parse cleanly.

Safe commands:

```bash
./ops/scripts/prelaunch-repo-check.sh
git status --short
git diff --check
bash -n ops/scripts/*.sh
test -f apps/frontend/site/favicon.ico
test -f apps/frontend/site/icon-192.png
test -f apps/frontend/site/icon-512.png
test -f apps/frontend/site/apple-touch-icon.png
test -f apps/frontend/site/site.webmanifest
```

Spot-check for obvious accidental commits:

```bash
git status --short
git ls-files | grep -E '(^|/)(\.env|.*\.jsonl)$' || true
```

The repo-only helper above does not read `.runtime/`, does not scan runtime
JSONL, and does not add dependencies. It checks whitespace, shell syntax,
tracked runtime files, likely committed secrets, and unsupported public payout
wording.

## B. Public Surface

Checklist:

- HTTPS returns `200`.
- `/api/health` returns OK.
- `/api/stats` returns JSON for pool-listing integrations.
- `/api/status` returns JSON for secondary compatibility.
- `/api/pool/summary` returns JSON.
- `/api/network/summary` returns JSON.
- `/api/payments` returns JSON.
- `/api/accepted-candidates` returns JSON.
- Mining guide page loads.

Safe commands:

```bash
curl -fsS https://pool.pepepow.net/ >/dev/null
curl -fsS https://pool.pepepow.net/connect.html >/dev/null
curl -fsS https://pool.pepepow.net/api/health
curl -fsS https://pool.pepepow.net/api/stats
curl -fsS https://pool.pepepow.net/api/status
curl -fsS https://pool.pepepow.net/api/pool/summary
curl -fsS https://pool.pepepow.net/api/network/summary
curl -fsS https://pool.pepepow.net/api/payments
curl -fsS https://pool.pepepow.net/api/accepted-candidates
```

Local API check when nginx or DNS is not part of the test:

```bash
curl -fsS http://127.0.0.1:8080/api/health
```

## C. Port Exposure

Checklist:

- `80/tcp` and `443/tcp` are public for web and HTTPS.
- `39333/tcp` is public only if mining is open.
- daemon RPC is private.
- wallet RPC is private.
- API bind is private if proxied by nginx.
- Redis is not public if ever added.

Safe commands:

```bash
ss -ltnp
ss -ltnp | grep 39333
```

Expected public surfaces are web, HTTPS, and Stratum `39333` when mining is
open. Daemon RPC, wallet RPC, Redis, runtime files, payout controls, and submit
controls must not be public.

## D. nginx Safety

Checklist:

- `nginx -t` passes.
- nginx blocks hidden files.
- nginx blocks raw runtime files.
- nginx blocks admin/control paths.
- nginx proxies only `/api` to the localhost API.
- Static frontend is served by nginx directly or through the frontend service,
  depending on the chosen deployment layout.

Safe commands:

```bash
nginx -t
```

Review the active nginx site before launch. It should expose public static
files and the read-only API, not private operational paths.

## E. systemd

Checklist:

- Stratum service is active when mining is open.
- API service is active.
- Core snapshot producer is active if used by the deployment.
- Frontend unit is optional if nginx serves `apps/frontend/site` directly.
- Optional timers are enabled only when the operator intentionally enabled them.

Safe commands:

```bash
systemctl status pepepow-pool-stratum.service --no-pager
systemctl status pepepow-pool-api.service --no-pager
systemctl status pepepow-pool-core.service --no-pager
systemctl status pepepow-pool-frontend.service --no-pager
systemctl status pepepow-pool-auto-payout.timer --no-pager
```

Do not enable or restart services from this checklist unless the launch plan
explicitly calls for it.

## F. Mining / Payout Truthfulness

Checklist:

- Dashboard does not claim guaranteed rewards.
- Payments page shows recorded payments only.
- Miner page does not show a fake pending balance.
- Accepted candidates are observation/lifecycle data, not payout guarantee.
- Accepted shares are presented separately from confirmed blocks.
- Pool-side share-rate estimate is not described as exact miner local hashrate.
- Public website does not expose operator payout or submit controls.

Safe commands:

```bash
grep -RniE "earned|guaranteed|payable balance|pending reward" apps/frontend/site || true
grep -RniE "daemon RPC|wallet RPC" apps/frontend/site || true
```

## G. Runtime Bounded Checks

Checklist:

- Use `tail` only for JSONL spot checks.
- no full JSONL `cat`.
- no pandas.
- no broad runtime scan.
- Do not inspect or publish private runtime files through the public website.

Safe examples:

```bash
tail -n 20 .runtime/live-stratum/share-events.jsonl
tail -n 20 .runtime/live-stratum/candidate-events.jsonl
```

Avoid:

```bash
cat .runtime/live-stratum/share-events.jsonl
python3 -c 'import pandas'
```

## Stop Conditions

Stop and review before launch if:

- any secret appears in `git status --short` or tracked files
- any runtime JSONL file is tracked
- HTTPS or `/api/health` fails
- daemon RPC or wallet RPC is reachable publicly
- nginx exposes runtime, admin, payout, or submit paths
- public pages imply guaranteed payout, pending balance, or confirmed blocks from
  accepted shares
