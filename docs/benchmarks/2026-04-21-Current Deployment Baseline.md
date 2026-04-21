## Current Deployment Baseline

This host currently treats the frontend as **optional** rather than required for the core mining baseline.

### Installed systemd units in the current baseline

- `pepepow-pool-core.service`
- `pepepow-pool-api.service`
- `pepepow-pool-stratum.service`

### Not installed in the current baseline

- `pepepow-pool-frontend.service`

### Operational meaning

The current validated deployment baseline is:

- daemon-template Stratum path active
- pool core active
- public API active
- frontend unit absent on this host

This means the core mining/API stack is considered healthy even when the
frontend systemd unit is not installed.

### Ops behavior aligned to this baseline

To match the current deployment reality:

- `ops/scripts/healthcheck.sh` skips the frontend probe when
  `pepepow-pool-frontend.service` is not installed
- `ops/scripts/restart-services.sh` skips the frontend restart when
  `pepepow-pool-frontend.service` is not installed
- if the frontend unit is installed later, both scripts continue to use the
  normal frontend check/restart path

### Boundary

This is a deployment-baseline clarification only.

It does **not** change:

- mining correctness
- candidate handling
- controlled submit behavior
- payout/accounting scope
- frontend deployment design

### Practical interpretation

For the current host, treat these as the minimum expected healthy services:

- `pepepow-pool-core.service`
- `pepepow-pool-api.service`
- `pepepow-pool-stratum.service`

A missing frontend unit on this host should be interpreted as
**baseline-consistent**, not as an operational failure.