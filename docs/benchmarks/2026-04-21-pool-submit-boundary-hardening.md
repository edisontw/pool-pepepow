# 2026-04-21 Pool Submit Boundary Hardening

## Scope

This note records the final worthwhile pool-side hardening patch found after the
PEPEPOW daemon-template reject path had already been narrowed past target math,
issued-job context alignment, and submit-time reconstruction.

The purpose of this change is not to re-open miner-side analysis or revisit
pool-side header reconstruction. It only tightens the Stratum submit protocol
boundary so malformed payloads are rejected early and classified cleanly.

This artifact does not claim a new mining-correctness breakthrough by itself.
It documents a narrow protocol-boundary closure patch and the resulting updated
status of the pool-side investigation.

---

## Prior Narrowed State

Before this patch, the following pool-side findings were already closed:

- estimated hashrate was decoupled from share difficulty
- PEPEPOW share-hash canonical byte-order handling was corrected
- previous-job assigned difficulty mismatch was corrected
- same-job target math was confirmed aligned
- issued daemon-template job context and submit-time reconstruction were
  confirmed aligned
- live reject evidence showed:
  - `issuedVsSubmitReconstructionMatch = true`
  - `header80Hex == independentAuthoritativeHeader80Hex`
  - `localComputedHash == independentAuthoritativeShareHash`

Operationally, this meant the remaining low-difficulty-share rejects were no
longer credibly explained by pool-side target derivation or pool-side
reconstruction mismatch.

---

## Hardening Gap Found

One worthwhile pool-side gap still remained in scope at the protocol boundary.

`mining.submit` validation was checking parameter presence, but it was not yet
fully enforcing the exact wire contract advertised during subscribe / job
negotiation.

Specifically, malformed payloads could pass deeper into later validation stages
instead of being rejected immediately as protocol-boundary errors.

The missing checks were:

- `extranonce2` was not enforced against negotiated `extranonce2_size`
- `ntime` was not required to be exactly 8-character hex
- `nonce` was not required to be exactly 8-character hex

This meant malformed submits were not always kept distinct from:

- `stale-job`
- `unknown-job`
- valid-but-`low-difficulty-share`

---

## Minimum Corrective Patch

A narrow boundary hardening patch was applied.

Changed files:

- `apps/pool-core/stratum_ingress.py`
- `tests/test_stratum_ingress.py`

Behavior change:

- reject malformed `mining.submit` payloads earlier at the protocol boundary
- require `extranonce2` to be hex and match negotiated `extranonce2_size`
- require `ntime` to be exactly 8-character hex
- require `nonce` to be exactly 8-character hex
- classify these cases cleanly as `malformed-submit`

This patch does **not** change:

- pool-side target math
- daemon-template job reconstruction
- candidate preparation
- `submitblock`
- payout logic

It is intentionally isolated to protocol-boundary validation only.

---

## Why This Patch Was Still Worth Doing

Although this patch is not the root cause of the remaining low-difficulty-share
rejects, it improves evidence quality and closes the last clearly useful
pool-side hardening gap in the narrowed path.

Benefits:

- malformed payloads are rejected immediately
- malformed submits stay clearly separated from stale or unknown job cases
- malformed submits stay clearly separated from valid-but-low-share rejects
- future miner-developer comparison is cleaner because the pool now enforces the
  exact submit wire contract at the boundary

In practice, this reduces ambiguity in later evidence collection.

---

## Validation

Focused unit tests were run with `python3 -m unittest`:

- `test_submit_with_malformed_params_is_rejected`
- `test_submit_with_wrong_extranonce2_width_is_rejected_as_malformed`
- `test_submit_with_non_hex_nonce_is_rejected_as_malformed`

All passed.

No additional live restart was required for this round because the patch only
changes malformed submit handling and does not alter the already-proven valid
submit reconstruction path.

---

## Risk

Risk is low.

This patch only tightens malformed payload rejection at the Stratum protocol
boundary. It does not modify valid-share hashing, target comparison, candidate
preparation, or submission flow.

The main regression risk would be only if a previously tolerated but actually
malformed client payload was relying on loose parsing. That is acceptable and is
consistent with the intended protocol contract.

---

## Updated In-Scope Conclusion

After this patch, no further worthwhile pool-side patch remains in the narrowed
submit target / reconstruction line.

Current conclusion:

- pool-side target math is not the remaining explanation
- pool-side issued-job vs submit-time reconstruction is not the remaining
  explanation
- pool-side submit-boundary hardening has now been tightened
- the remaining low-difficulty-share rejects are no longer credibly explained by
  pool-side target math, reconstruction, or malformed submit handling

A separate miner-side anomaly may still exist, but that path is treated as an
upstream miner-developer concern rather than the main pool-side investigation
for this round.

---

## Rollback

Revert:

- `apps/pool-core/stratum_ingress.py`
- `tests/test_stratum_ingress.py`

Because the patch is isolated to protocol-boundary validation, rollback is
simple and low-risk.

---

## Suggested Commit

### Commit title

`Harden stratum submit field validation`

### Commit body

`Enforce the advertised submit wire contract at the pool boundary.

Reject malformed mining.submit payloads early by validating:
- extranonce2 is even-length hex
- extranonce2 matches negotiated extranonce2_size
- ntime is 8-char hex
- nonce is 8-char hex

Add focused tests to keep malformed submits distinct from stale, unknown,
and valid-but-low-share submits without revisiting target math or header
reconstruction.`
