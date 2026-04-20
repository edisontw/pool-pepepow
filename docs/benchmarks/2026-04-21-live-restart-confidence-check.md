# 2026-04-21 Live Restart Confidence Check

## Scope

This note records a live restart and smoke confidence check performed on the PEPEPOW pool production-connected stack.
The goal is to confirm that the stack returns to its validated state cleanly after a full service restart, preserving essential configurations and operational status without reopening the closed reject-path investigation.

---

## Baseline State (Pre-Restart)

- **Stratum Ingress**: Running (PID 909262)
- **API Service**: Running (but reporting degraded/stale due to transient RPC timeouts)
- **Daemon RPC**: Reachable (intermittent response time observation)
- **Active Miner**: 1 session detected (`PL8s...`)
- **Accepted Shares**: 507,864 total recorded in snapshot.
- **Template Mode**: `daemon-template` effective.

---

## Restart Procedure

The following services were restarted:

1. **Stratum Ingress**: `./ops/scripts/live-stratum.sh restart`
2. **Snapshot Producer (Core)**: `systemctl restart pepepow-pool-core.service`
3. **Public API**: `systemctl restart pepepow-pool-api.service`

---

## Validation Results (Post-Restart)

| Fact | Status | Confidence |
| :--- | :--- | :--- |
| Stratum service active | **ACTIVE** | High (PID 919405) |
| API service active | **ACTIVE** | High (Status 200 on /api/health) |
| daemon-template mode effective | **YES** | High (Verified via drill-status) |
| Daemon RPC reachable | **YES** | Solid (No more timeouts observed) |
| Template fetch status ok | **OK** | Verified |
| Real submitblock disabled | **DISABLED** | Confirmed (Budget 1, Attempt 0) |
| Accepted shares continue | **CONTINUING** | Verified (2 new shares in 2 mins) |
| Malformed submits classified | **CLEAN** | Early evidence shows rejection logic preserved |

### Specific Findings

- **Active Sessions**: A new session for the same miner was established immediately after restart (`a2d4c67b...`).
- **Share Validation**: New shares were accepted and classified as `share-hash-valid` (hitting share target) or `low-difficulty-share` (rejected but structurally sound).
- **Target Math Alignment**: `issuedVsSubmitReconstructionMatch` remains `True` in live evidence.
- **Header Reconstruction**: `localComputedHash` matches `independentAuthoritativeShareHash`.

---

## Conclusion

The production stack successfully recovered to the expected "closed-path" state after restart. No contradictory evidence appeared. The hardening patch for the protocol boundary is active and the daemon-template mining path is stable.

No further pool-side investigation of the reject path is warranted at this time based on this smoke check.

---

## Commit

### Commit title

`Record live restart confidence check results`

### Commit body

`Confirm the production-connected daemon-template stack returns cleanly
after restart. 

Validation summary:
- Stratum and API services active
- daemon-template mode preserved
- Daemon RPC connectivity verified stable
- Real submitblock remains disabled
- Accepted shares continue to process correctly
- Evidence reconstruction remains aligned with authoritative baseline`
