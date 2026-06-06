# Public HTTPS Nginx Deployment (2026-06-06)

- **Public HTTPS site online** – `https://pool.pepepow.net` returns HTTP 200 with valid TLS certificate.
- **Nginx serves static frontend directly** from `apps/frontend/site/` (no separate frontend service unit required).
- **API reverse‑proxy** – `/api/*` is proxied to the backend at `127.0.0.1:8080`.
- **Frontend systemd unit remains optional/absent** – the site works without a dedicated frontend service.
- **Stratum unchanged** – read‑only status, real submit disabled.
- **Real submit default‑off** – `real_submit_enabled: false` confirmed.
- **Payout and round accounting paused** – no payout activity, round accounting remains paused.

*All smoke‑tests passed and the repository is clean.*
