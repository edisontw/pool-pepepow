## Provenance

These static libraries are vendored for the local PEPEPOW hash bridge used by:

- [`../../pepepow_pow.py`](/home/ubuntu/pool-pepepow/apps/pool-core/pepepow_pow.py)
- [`../../pepepow_pow_helper.c`](/home/ubuntu/pool-pepepow/apps/pool-core/pepepow_pow_helper.c)

Source provenance:

- source repo: Hoosat stratum bridge
- source path: `src/pow/libs/aarch64-linux/`
- artifacts:
  - `libhoohash.a`
  - `libblake3.a`

Why these libs are vendored:

- this host does not provide a separately installed reusable `libhoohash` or
  `libblake3`
- `PEPEPOWd` is a stripped executable, not a supported stable library ABI
- vendoring keeps the runtime bridge self-contained and independent from any
  `/tmp` exploration checkout

Authority on this host:

- installed `PEPEPOWd` / `PEPEPOW-cli` version: `v2.9.0.4-c1394e6`
- local daemon RPC and real chain behavior are the primary correctness checks

If these libs are updated, revalidate at minimum:

1. the known-chain-vector hash test in [`../../../tests/test_stratum_ingress.py`](/home/ubuntu/pool-pepepow/tests/test_stratum_ingress.py)
2. local bridge build/load on aarch64
3. production-path `shareHashValidationMode` and counter coherence in
   `activity-snapshot.json` and `/api/health`
4. one live daemon-template smoke with the external miner across restart
