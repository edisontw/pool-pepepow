# 2026-05-13 Controlled Submit Readiness Drill

## Summary

This record documents the first successful end-to-end controlled enable/restore readiness drill after fixing the non-interactive `systemd-restart` path for the live PEPEPOW daemon-template Stratum service.

The drill verified:

* the service can safely enter a short real-submit-enabled window
* the service can safely restore the default-off baseline
* daemon-template readiness remains intact during the bounded window
* the one-shot guardrail (`MAX_SENDS=1`) remains preserved
* the service remains under single-instance systemd ownership throughout

This drill did **not** produce a fresh candidate or a real `submitblock` attempt.

It is an operations/safety verification milestone only.

---

## Scope

This drill was intentionally narrow.

It does **not** claim:

* block discovery
* payout readiness
* round tracking correctness
* mature block lifecycle handling
* submit correctness beyond the already-closed lines
* candidate closure success on a fresh candidate

The purpose was only to validate the controlled operational path:

```text
disabled -> short enabled window -> safe restore
```

---

## Background

A prior readiness attempt failed because:

```text
systemctl restart pepepow-pool-stratum.service
```

required interactive authentication.

The restart path was corrected by:

* adding a narrow `sudoers` drop-in for the Stratum service
* updating `live-stratum.sh systemd-restart` to use:

```bash
sudo -n /usr/bin/systemctl ...
```

The corrected restart path was already validated separately before this drill.

---

## Preflight

Preflight completed successfully before enabling the window.

### Repository State

```text
git status --short: clean
```

### Listener Ownership

Exactly one listener remained on:

```text
0.0.0.0:39333
```

Listener PID matched the systemd-managed process.

### Preflight Drill Status

`./ops/scripts/live-stratum.sh drill-status`

Confirmed:

```text
drill_status: ready
template_mode_effective: daemon-template
template_fetch_status: ok
template_daemon_rpc_reachable: True

real_submit_enabled: False
real_submit_send_budget: 1
real_submit_attempt_count: 0
real_submit_sent_count: 0
real_submit_error_count: 0
```

### Preflight Freshness Audit

`./ops/scripts/live-stratum.sh candidate-freshness-audit 200`

Confirmed:

```text
latest_submit_readiness_status: disabled
```

---

## Controlled Enable Window

### Enable Command Timestamp

```text
2026-05-13T14:33:39Z
```

### Enable Command

```bash
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=true \
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1 \
./ops/scripts/live-stratum.sh systemd-restart
```

### Restart Transition

| Stage             | MainPID  |
| ----------------- | -------- |
| Pre-enable        | `871189` |
| Enabled window    | `874557` |
| Restored baseline | `875597` |

### Enabled Service Start

```text
2026-05-13 14:33:44 UTC
```

### Enabled-Window Verification

Immediately after restart:

```text
real_submit_enabled: True
real_submit_send_budget_remaining: 1
real_submit_attempt_count: 0
real_submit_sent_count: 0
real_submit_error_count: 0
```

Daemon-template readiness remained healthy:

```text
template_mode_effective: daemon-template
template_fetch_status: ok
template_daemon_rpc_reachable: True
```

---

## Observation Window

Observation remained intentionally short and bounded.

Approximate duration:

```text
55 seconds
```

Window:

```text
2026-05-13T14:33:44Z
through
2026-05-13T14:34:39Z
```

Bounded observation commands:

```bash
./ops/scripts/live-stratum.sh drill-status
./ops/scripts/live-stratum.sh candidate-events 10
./ops/scripts/live-stratum.sh candidate-freshness-audit 200
```

No unbounded runtime log scans were used.

---

## Stop Trigger

The stop condition was:

```text
60 seconds elapsed without meaningful event
```

No fresh candidate appeared during the enabled window.

No new:

* submit attempt
* submit send
* submit error
* stale-prevblk event

was produced during this drill.

---

## Candidate / Submit Evidence

### Real Submit Attempt

```text
No
```

### Real Submit Sent

```text
No
```

### Real Submit Error

```text
No
```

### Fresh Candidate During Window

```text
No
```

### Stale Prevhash Protection Triggered

```text
No (during this drill)
```

Historical bounded-tail evidence still contained older:

```text
submit-skipped-stale-prevblk
```

rows from earlier activity, but no fresh stale-prevblk event was generated during this enabled window.

---

## Restore Sequence

### Restore Command Timestamp

```text
2026-05-13T14:34:46Z
```

### Restore Command

```bash
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=false \
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1 \
./ops/scripts/live-stratum.sh systemd-restart
```

### Restored Service Active

```text
2026-05-13 14:34:48 UTC
```

---

## Final Safety State

Post-restore verification confirmed the expected safe baseline.

### Drill Status

```text
real_submit_enabled: False
real_submit_send_budget: 1
real_submit_attempt_count: 0
real_submit_sent_count: 0
real_submit_error_count: 0

template_mode_effective: daemon-template
template_fetch_status: ok
template_daemon_rpc_reachable: True
```

### Freshness Audit

```text
latest_submit_status: submit-disabled-flag-off
latest_submit_readiness_status: disabled
```

### launch.env

```bash
PEPEPOW_ENABLE_REAL_SUBMITBLOCK=false
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS=1
```

### Listener Ownership

Exactly one listener remained on:

```text
0.0.0.0:39333
```

Listener PID again matched the systemd-managed process.

---

## Operational Interpretation

This drill successfully verified the operational safety path:

```text
disabled
-> controlled short enable
-> bounded observation
-> safe restore
```

The most important conclusions are:

1. the corrected `systemd-restart` path now works non-interactively
2. daemon-template readiness survives the short enabled window
3. the one-shot budget remains intact
4. the default-off baseline can be restored cleanly
5. no accidental submit attempt occurred during the bounded window

The current state remains:

```text
candidate wait state
```

and not:

```text
confirmed submit correctness milestone
```

because no fresh candidate appeared during the enabled interval.

---

## Remaining Boundary

Still not completed:

* confirmed pool-found block
* payout accounting
* mature block lifecycle tracking
* round accounting
* production payout readiness
* fresh candidate closure during an enabled window

Do not reopen already-closed correctness lines unless contradictory evidence appears:

* target math
* endian comparator
* merkle reconstruction
* header reconstruction
* submit-time job alignment
* daemon-template reconstruction path

---

## Current Recommended Baseline

Keep the service on the current safe baseline:

```text
real_submit_enabled = False
PEPEPOW_REAL_SUBMITBLOCK_MAX_SENDS = 1
template_mode_effective = daemon-template
template_fetch_status = ok
```

Do not repeatedly reopen short enabled windows without a specific operational reason.

The next meaningful event should be:

```text
a fresh non-controlled candidate
```

followed by the normal bounded follow-up flow.

---

## Suggested Commit

### Commit Title

```text
Record controlled submit readiness drill
```

### Commit Body

```text
Document the 2026-05-13 controlled real-submit readiness drill.

Record that the fixed systemd-restart path can enter and restore a short
enabled window with MAX_SENDS=1 while preserving daemon-template readiness.

No real submit attempt occurred because no fresh candidate appeared during the
bounded window, and the service was restored to the default-off baseline.
```
