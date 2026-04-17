# Pool Core

This directory contains the minimal read-only internal data pipeline for the
current PEPEPOW round.

## Implemented In This Round

- daemon read-only JSON-RPC adapter
- conservative snapshot producer
- daemon-independent Stratum ingress
- synthetic/fake Stratum v1 job broadcast for miner compatibility
- optional daemon-backed block template polling with synthetic-safe fallback
- atomic snapshot writes for the API layer
- degraded fallback behavior when daemon RPC is unavailable
- local JSONL share ingest for testing-mode and Stratum activity data
- lightweight miner/worker accounting for runtime snapshots
- additive activity snapshot output for API overlay
- bounded JSONL rotation/retention and snapshot-first replay

## Not Implemented In This Round

- real share validation
- candidate block handling or `submitblock`
- payout-grade accounting
- payout automation
- Redis-backed runtime state

## RPC Boundary

Only the producer talks to daemon RPC. The frontend must never call daemon RPC
and nginx must never proxy it publicly.

Configure RPC explicitly in `~/.PEPEPOWcore/PEPEPOW.conf`:

```ini
server=1
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcport=8834
rpcuser=change-me
rpcpassword=change-me
```

After editing `PEPEPOW.conf`, stop `PEPEPOWd` and start it again. Do not assume
RPC settings hot-reload.

Back up the daemon config before changing it:

```bash
mkdir -p ~/.PEPEPOWcore/backups
cp ~/.PEPEPOWcore/PEPEPOW.conf \
  ~/.PEPEPOWcore/backups/PEPEPOW.conf.$(date -u +%Y%m%dT%H%M%SZ)
```

## Snapshot Contract

The producer writes JSON matching:

`contracts/pool-snapshot.schema.json`

The local testing-mode share ingest accepts JSONL events matching:

`contracts/share-event.schema.json`

The daemon-independent Stratum activity snapshot is described by:

`contracts/activity-snapshot.schema.json`

Recommended output path:

`/var/lib/pepepow-pool/pool-snapshot.json`

Recommended local share log path:

`/var/lib/pepepow-pool/share-events.jsonl`

Recommended activity snapshot path:

`/var/lib/pepepow-pool/activity-snapshot.json`

Keep the daemon RPC private:

- `rpcbind=127.0.0.1`
- `rpcallowip=127.0.0.1`
- do not expose `8834` through nginx, firewall rules, or a public interface

## Producer

Run once:

```bash
cd /home/ubuntu/pool-pepepow/apps/pool-core
python3 producer.py --once
```

Run as a long-lived service through systemd in deployment.

## Stratum Ingress

Run locally:

```bash
cd /home/ubuntu/pool-pepepow/apps/pool-core
python3 stratum_ingress.py
```

Current minimal scope:

- accepts `mining.subscribe`
- returns a standard Stratum v1 subscription tuple list plus extranonce fields
- accepts `mining.extranonce.subscribe` as a no-op compatibility method
- accepts `mining.authorize`
- pushes synthetic `mining.set_difficulty`
- pushes synthetic `mining.notify`
- can attach daemon template context to jobs when `PEPEPOW_POOL_CORE_TEMPLATE_MODE=daemon-template`
- accepts `mining.submit`
- always accepts submitted shares
- writes every submitted share to JSONL with `source="stratum"`
- writes a daemon-independent activity snapshot for the API to overlay
- exposes template fetch/job-cache status through the activity snapshot
- rotates JSONL by size and replays bounded retained tail on restart

Not implemented in this round:

- real difficulty management
- daemon/template validation
- real candidate validation or `submitblock`
- payouts

Important boundaries:

- synthetic job mode is fake work for protocol compatibility only
- submitted shares are non-validated
- activity output is not blockchain verified
- bounded replay is snapshot-first and only restores retained rolling tail

## PEPEPOW Hash Bridge

The local share-hash classification bridge is intentionally small:

- [`stratum_ingress.py`](/home/ubuntu/pool-pepepow/apps/pool-core/stratum_ingress.py)
- [`pepepow_pow.py`](/home/ubuntu/pool-pepepow/apps/pool-core/pepepow_pow.py)
- [`pepepow_pow_helper.c`](/home/ubuntu/pool-pepepow/apps/pool-core/pepepow_pow_helper.c)
- vendored static libraries under
  [`libs/aarch64-linux/`](/home/ubuntu/pool-pepepow/apps/pool-core/libs/aarch64-linux)

Authority and provenance:

- The installed daemon/client on this host are the primary authority:
  `PEPEPOWd` / `PEPEPOW-cli` `v2.9.0.4-c1394e6`
- Runtime correctness is checked against local daemon RPC and real chain data.
- `PEPEPOWd` is a stripped executable, not a stable reusable library ABI, so the
  pool does not link against the daemon binary directly.
- The vendored `libhoohash.a` and `libblake3.a` were copied from Hoosat's
  aarch64 stratum-bridge build so the runtime bridge does not depend on any
  `/tmp` exploration checkout.

Current runtime dependency boundary:

- runtime does not import code from `/tmp/HTND`, `/tmp/htn-stratum-bridge`, or
  other exploration trees
- the helper builds a local
  `/home/ubuntu/pool-pepepow/.runtime/pool-core-build/libpepepow_pow.so`
  from repo-vendored sources and static libraries

Current non-essential artifacts:

- `/home/ubuntu/pool-pepepow/.runtime/pool-core-build/libpepepow_pow.so` is a
  generated artifact and can be rebuilt
- `/home/ubuntu/pool-pepepow/.runtime/pool-core-build/blake3.h` is not needed
  for runtime; it is only a leftover build copy if present

## Reindex Behavior

When `PEPEPOWd` is reindexing, the producer may still emit a valid runtime
snapshot. In that state:

- `meta.chainState` should be `reindexing` or `syncing`
- `network.synced` should remain `false`
- chain metrics are only for path verification, not final acceptance
- local share/activity data stays separate from chain data
