# systemd

These unit files target the `/opt/pepepow-pool` deployment layout on Ubuntu.

- `pepepow-pool-core.service` runs the runtime snapshot producer
- `pepepow-pool-stratum.service` runs the daemon-independent Stratum ingress and activity snapshot writer
- `pepepow-pool-api.service` serves the public API from runtime/fallback snapshots
- `pepepow-pool-frontend.service` serves the static frontend
