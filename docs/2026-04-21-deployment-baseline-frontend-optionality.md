# 2026-04-21 Deployment Baseline and Frontend Optionality

## Scope

This note clarifies the current deployment baseline on the present host so that
health checks, restart flows, and future smoke interpretation do not misclassify
an absent frontend service as a pool failure.

This is an operations / documentation clarification only.

It does **not** change:

- mining correctness
- share validation
- candidate preparation
- `submitblock`
- block-state tracking
- payout scope

---

## Current Host Baseline

The currently installed pool-related systemd units on this host are:

- `pepepow-pool-core.service`
- `pepepow-pool-api.service`
- `pepepow-pool-stratum.service`

The following unit is **not** installed on this host:

- `pepepow-pool-frontend.service`

Operationally, this means the current host baseline is a valid partial web/API
and mining deployment without a local frontend service managed by systemd.

---

## Interpretation Rule

For this host, absence of `pepepow-pool-frontend.service` must be interpreted as
an expected deployment variant, not as an operational failure.

So when evaluating local ops scripts on this machine:

- Stratum active = expected
- API active = expected
- pool-core active = expected
- frontend unit absent = expected

A missing frontend unit on this host does **not** imply:

- mining outage
- API outage
- daemon-template failure
- candidate-path regression
- payout regression

---

## Script Behavior Clarification

The local ops behavior has already been aligned to this host baseline:

- `ops/scripts/healthcheck.sh` intentionally skips the frontend probe when
  `pepepow-pool-frontend.service` is not installed
- `ops/scripts/restart-services.sh` intentionally skips the frontend restart
  when `pepepow-pool-frontend.service` is not installed

This behavior is intentional and correct for the current deployment variant.

It should be read as:

- optional frontend on this host
- not a failed health check
- not a partial restart failure

---

## Why This Clarification Exists

Earlier health / restart interpretation could produce misleading noise by
implicitly assuming that every deployment must include:

- core
- stratum
- API
- frontend

That assumption is not true for the current host.

Documenting the actual installed-unit baseline prevents future checks from
misreporting an absent frontend as a broken deployment when the mining and API
services are healthy.

---

## Practical Validation Baseline

When validating this host, the minimum expected service baseline is:

- `pepepow-pool-core.service` active
- `pepepow-pool-api.service` active
- `pepepow-pool-stratum.service` active

And, for the current deployment variant:

- `pepepow-pool-frontend.service` may be absent without counting as failure

If a frontend unit is installed on a future host or later on this host, then
frontend health and restart behavior should resume normal enforcement.

---

## Boundary

This note is only about deployment-baseline interpretation.

It does not widen current project scope into:

- frontend feature work
- public status redesign
- payout/accounting work
- new monitoring infrastructure
- miner-side diagnosis

---

## Rollback

If this clarification becomes outdated because the frontend unit is later
installed as part of the normal host baseline, this note can be updated or
removed.
