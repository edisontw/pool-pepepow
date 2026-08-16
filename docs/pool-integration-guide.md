# PEPEPOW Third-Party Pool Integration Guide

This document is for external mining-pool operators who want to add PEPEPOW to
their own pool stack. It is **not** a deployment guide for the PEPEPOW Lab Pool.
For deploying this repository as a pool, use
[`deploy-pepepow-pool-quickstart.md`](deploy-pepepow-pool-quickstart.md).

The goal of this guide is to reduce integration work by pointing to the working,
production-tested PEPEPOW reference paths already present in this repository.

## Integration Summary

| Item | Reference |
| --- | --- |
| Project | PEPEPOW |
| Mining algorithm | `hoohashv110-pepew` |
| Share hash mode used by this pool | `hoohashv110-pepew-header80` |
| Pool protocol | Stratum V1-style JSON-RPC |
| Block template source | daemon `getblocktemplate` |
| Candidate submission | daemon `submitblock` |
| Lab Pool endpoint | `pool.pepepow.net:39333` |
| Lab Pure SOLO endpoint | `pool.pepepow.net:39334` |
| Public pool API | `https://pool.pepepow.net/api/` |

The Lab Pool ports above are reference endpoints only. Third-party operators can
choose their own public Stratum ports.

## Important Compatibility Note: Difficulty Baseline

Do not assume the Bitcoin Stratum diff-1 target.

The current PEPEPOW pool implementation uses this miner-facing diff-1 target:

```text
0000ffff00000000000000000000000000000000000000000000000000000000
```

The implementation explicitly notes that the Bitcoin diff-1 target is 65,536x
stricter and would reject ordinary PEPEPOW pool shares.

Reference:
[`apps/pool-core/stratum_ingress.py`](../apps/pool-core/stratum_ingress.py)

This is one of the first items a third-party pool should verify when adapting an
existing Stratum implementation.

## Proof-of-Work / Header Layout

The working PEPEPOW share-validation path hashes an 80-byte block header with
HooHash V110.

Header layout used by the reference implementation:

```text
version     4 bytes
prevHash   32 bytes
merkleRoot 32 bytes
ntime       4 bytes
bits        4 bytes
nonce       4 bytes
-------------------
total      80 bytes
```

Reference implementation:

- [`apps/pool-core/hoohash.c`](../apps/pool-core/hoohash.c)
- [`apps/pool-core/hoohash.h`](../apps/pool-core/hoohash.h)
- [`apps/pool-core/pepepow_pow_helper.c`](../apps/pool-core/pepepow_pow_helper.c)
- [`apps/pool-core/stratum_ingress.py`](../apps/pool-core/stratum_ingress.py)

Before opening a pool publicly, validate your HooHash implementation against the
known vectors and tests in this repository rather than relying only on a miner
connection test.

Useful references:

- [`verify_known_vector`](../verify_known_vector)
- [`test_v110`](../test_v110)
- [`tests/test_stratum_ingress.py`](../tests/test_stratum_ingress.py)

## Daemon Integration

The reference pool obtains live mining work from the PEPEPOW daemon using
`getblocktemplate` and submits valid network candidates using `submitblock`.

Relevant code:

- [`apps/pool-core/daemon_rpc.py`](../apps/pool-core/daemon_rpc.py)
- [`apps/pool-core/template_jobs.py`](../apps/pool-core/template_jobs.py)

A typical local-only daemon RPC configuration used by this repository is:

```ini
server=1
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcport=8834
rpcuser=change-me
rpcpassword=change-me
```

**Do not expose daemon RPC publicly.** A third-party pool should keep daemon RPC
and wallet RPC on private/local interfaces and expose only its miner-facing
Stratum service and any intentionally public read-only API.

## Stratum Compatibility

The current reference server implements the familiar Stratum V1 workflow.
Operators adapting an existing pool should compare their wire format against
[`apps/pool-core/stratum_protocol.py`](../apps/pool-core/stratum_protocol.py).

### Subscribe

`mining.subscribe` returns:

```text
subscriptions
extranonce1
extranonce2_size
```

The current reference implementation uses a 4-byte `extranonce2` size.

### Authorization

`mining.authorize` accepts the miner login. The reference pool supports:

```text
WALLET
WALLET.WORKER
```

### Difficulty

The pool sends:

```text
mining.set_difficulty
```

Use the PEPEPOW difficulty baseline described above. Do not silently reuse a
Bitcoin diff-1 conversion.

### Mining Jobs

The reference `mining.notify` parameters are:

```text
job_id
prevhash
coinb1
coinb2
merkle_branch
version
nbits
ntime
clean_jobs
```

The reference code also performs the prevhash formatting expected by connected
miners. Copying the field order without matching byte/word order is not enough;
compare actual notify payloads and submitted headers during integration testing.

### Share Submission

A submitted share should be checked for at least:

1. known/current job
2. valid submit identity
3. duplicate submit
4. structurally valid fields
5. HooHash V110 header hash
6. assigned share target
7. network target / candidate status

A share that satisfies the pool target is an accepted pool share. A share that
also satisfies the daemon/network target is a block candidate and should proceed
to the guarded `submitblock` path.

Reference:
[`apps/pool-core/stratum_ingress.py`](../apps/pool-core/stratum_ingress.py)

## Coinbase and Template Handling

Do not hard-code a generic Bitcoin-family coinbase and assume it is sufficient.
Use the live daemon template and compare your generated block against the working
PEPEPOW template/job implementation.

Reference:
[`apps/pool-core/template_jobs.py`](../apps/pool-core/template_jobs.py)

This repository also contains successful submitblock validation records under
[`docs/benchmarks/`](benchmarks/), including controlled candidate submission and
mainnet Pool/SOLO lifecycle tests.

## Minimal Integration Test Sequence

A third-party pool should complete this sequence before announcing PEPEPOW
support:

1. **Daemon sync** — daemon is on the current chain tip and exposes RPC only on a private interface.
2. **Template fetch** — repeated `getblocktemplate` calls return usable current work.
3. **PoW vector test** — local HooHash V110 output matches known reference vectors.
4. **Stratum subscribe** — a real PEPEPOW miner completes `mining.subscribe`.
5. **Authorization** — `WALLET` and, if supported, `WALLET.WORKER` are handled correctly.
6. **Notify** — the miner receives valid `mining.set_difficulty` and `mining.notify` messages.
7. **Share validation** — ordinary valid shares are accepted at the assigned PEPEPOW target.
8. **Invalid-share tests** — bad nonce/job/duplicate/stale submissions are rejected correctly.
9. **Candidate detection** — a network-target share is classified as a candidate.
10. **Submitblock** — the reconstructed block is accepted through daemon `submitblock`.
11. **Lifecycle follow-up** — accepted/orphan/mature state is tracked correctly.
12. **Accounting/payout** — pool-specific reward and payout logic is verified separately before enabling automatic sends.

Do not treat a successful TCP connection or Stratum authorization as proof that
the integration is complete. The critical validation is an end-to-end
mining-to-accepted-block path.

## Working Reference Paths

For operators who want to inspect a known working implementation, start with:

```text
apps/pool-core/stratum_protocol.py
apps/pool-core/stratum_ingress.py
apps/pool-core/template_jobs.py
apps/pool-core/daemon_rpc.py
apps/pool-core/hoohash.c
apps/pool-core/pepepow_pow_helper.c
```

Configuration references:

```text
config/coins/pepepow.json
ops/env/pool-core.env.example
apps/pool-core/config.example.toml
```

Validation references:

```text
tests/test_stratum_ingress.py
docs/benchmarks/
docs/runbooks/controlled-live-submitblock.md
```

## Public Reference Endpoints

Current Lab Pool reference services:

```text
Pool Stratum
stratum+tcp://pool.pepepow.net:39333

Pure SOLO Stratum
stratum+tcp://pool.pepepow.net:39334
```

Read-only API examples:

```text
GET https://pool.pepepow.net/api/health
GET https://pool.pepepow.net/api/network/summary
GET https://pool.pepepow.net/api/stats
GET https://pool.pepepow.net/api/status
```

These endpoints are useful for comparison and monitoring, but a third-party pool
should run its own daemon and validation path rather than depending on the Lab
Pool backend for consensus-sensitive work.

## Security Requirements

At minimum:

- keep daemon RPC private
- keep wallet RPC private
- never expose payout or `submitblock` controls through a public admin endpoint
- separate public status APIs from private operator controls
- validate candidate reconstruction before submission
- use replay/idempotency protection for payout records
- test payout logic independently from share acceptance
- keep a manual disable path for candidate submission and wallet sends

The Lab Pool architecture and runbooks provide examples, but third-party pools
should adapt these controls to their own infrastructure.

## Support and Contribution

If a pool operator finds a PEPEPOW-specific compatibility issue, open a GitHub
issue in this repository with:

- pool software / framework
- platform and architecture
- miner software used for testing
- sanitized Stratum request/response samples
- assigned difficulty
- rejection reason or daemon RPC error
- relevant block/template height

Do **not** post RPC credentials, wallet private keys, seed phrases, or private
operator configuration.

Contributions that improve interoperability, test vectors, deployment notes, or
third-party pool compatibility are welcome.
