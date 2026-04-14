# 2026-04-14 External GPU Synthetic Stratum Smoke

## Scope / Boundary

This artifact records one external miner smoke run against the current
daemon-independent synthetic Stratum preflight path.

It verifies protocol compatibility and external connectivity only. It does not
verify real mining correctness.

This run remains:

- synthetic / fake work
- daemon-independent
- non-validated
- not blockchain verified
- not backed by daemon templates
- not a candidate block path
- not `submitblock`
- not payout-related

---

## Tested Miner

- miner: `HTN GPU Miner`
- version: `hoo_gpu 1.4.7`

---

## Provenance / Source

- source references: `https://pepepow.org/mining/ ; https://htn.foztor.net/hoo_gpu.tar.gz`
- acquisition method:

```bash
wget -c https://htn.foztor.net/hoo_gpu.tar.gz -O - | tar -xz
```

---

## Environment / Platform

- miner environment: `x86_64 Ubuntu + NVIDIA GPU`
- pool endpoint used by external miner: `192.9.160.179:39333`
- preflight listener observed: `0.0.0.0:39333`
- external remote address observed in accepted-share evidence: `36.227.95.132:49832`

---

## Exact Commands Used

Pool preflight command:

```bash
PEPEPOW_PREFLIGHT_PUBLIC_HOST=192.9.160.179 \
PEPEPOW_PREFLIGHT_SHARE_DIFFICULTY=0.000001 \
/home/ubuntu/pool-pepepow/ops/scripts/run-stratum-preflight.sh
```

Miner command:

```bash
./hoo_gpu -o stratum+tcp://192.9.160.179:39333 -u PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD -gpu-id 0 -p x --pepepow
```

---

## Observed Connection / Protocol Behavior

- external miner connected successfully to the synthetic preflight endpoint
- synthetic `mining.set_difficulty` was observed indirectly from accepted share
  records carrying `difficulty=1e-06`
- synthetic `mining.notify` was observed indirectly from accepted share records
  carrying `jobId`
- repeated notify/job rollover was observed from
  `job-0000000000000001` to `job-0000000000000002`
- the miner continued submitting accepted synthetic shares after rollover
- no disconnect, parse error, protocol mismatch, or hang evidence was found in
  the retained pool-side artifacts for this run

This smoke proves external synthetic Stratum connectivity and synthetic
accepted-share compatibility only. It does not prove real template correctness
or real share validation.

---

## Accepted Synthetic Share Evidence

Evidence source:

- `/tmp/pepepow-preflight/share-events.jsonl`
- `/tmp/pepepow-preflight/activity-snapshot.json`
- `/tmp/pepepow-preflight/stratum.log`

Observed facts from retained artifacts:

- accepted synthetic submits: `34`
- time window: `2026-04-14T13:07:00Z` to `2026-04-14T13:07:07Z`
- distinct job IDs: `2`
- observed difficulty: `1e-06`
- wallet: `PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD`
- worker: `default`
- `syntheticWork = true`
- `shareValidationMode = "none"`
- `blockchainVerified = false`

Important caveat:

- these are accepted synthetic shares only
- they are not validated shares
- they are not blockchain verified
- they do not imply correct daemon-backed work, valid block headers, candidate
  blocks, or real block production

---

## Current Verified Now

- external synthetic Stratum connectivity from a real external GPU miner
- compatibility with synthetic `mining.set_difficulty`
- compatibility with repeated synthetic `mining.notify`
- compatibility across synthetic job rollover
- accepted synthetic shares from a real external GPU miner

---

## Not Yet Implemented

- real daemon-backed work or template retrieval
- real share validation
- candidate block detection
- `submitblock`
- payout / round / balance tracking

---

## Risks / Remaining Gaps

- synthetic acceptance still does not imply valid shares
- this smoke does not prove real mining correctness
- this smoke does not prove block candidacy or block production
- this smoke does not change current scope into a full pool
- external reachability issues in this phase may still be caused by OCI or host
  firewall exposure rather than miner protocol behavior
