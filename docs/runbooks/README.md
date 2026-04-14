# Runbooks

- local development: `../local-development.md`
- Oracle Ubuntu deployment: `../oracle-ubuntu-deployment.md`
- snapshot pipeline: `./snapshot-pipeline.md`
- Stratum activity ingest: `./stratum-activity-ingest.md`
- external GPU smoke benchmark: `../benchmarks/2026-04-14-external-gpu-stratum-smoke.md`
- helper scripts: `../../ops/scripts/`

Current runbooks cover:

- daemon-aware runtime snapshots
- daemon-independent Stratum ingress
- activity snapshot overlay behavior
- local verification and stress testing
- external synthetic miner compatibility evidence

Block processing and payout recovery runbooks still do not exist. Share
accounting now has a daemon-independent Stratum ingress path in addition to the
older producer-side local JSONL ingest path.
