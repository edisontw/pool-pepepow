# Frontend

This directory contains the public PEPEPOW pool website skeleton.

## Scope

- Static multi-page frontend
- No Node.js build step
- Reads public API endpoints only
- Does not talk to daemon RPC, Redis, or payout tooling

## Pages

- `/` dashboard
- `/blocks.html`
- `/payments.html`
- `/miner.html`
- `/connect.html`

## Local Run

```bash
cd /home/ubuntu/pool-pepepow/apps/frontend/site
python3 -m http.server 3000
```

The site defaults to reading the API from `/api`. To override this without editing source, copy:

`runtime-config.example.json` -> `runtime-config.json`

and set `apiBaseUrl`.
