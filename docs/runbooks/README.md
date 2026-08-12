# Runbooks

Current operator/deployer references:

- local development: `../local-development.md`
- Oracle Ubuntu deployment: `../oracle-ubuntu-deployment.md`
- prelaunch checklist: `./prelaunch-checklist.md`
- snapshot pipeline: `./snapshot-pipeline.md`
- Stratum activity ingest: `./stratum-activity-ingest.md`
- Pure SOLO production submit/restart: `./pure-solo-production-submit.md`
- controlled submitblock reference: `./controlled-live-submitblock.md`
- reward calculator and log maintenance: `./reward-calculator-and-log-maintenance.md`
- helper scripts: `../../ops/scripts/`

The current production stack includes Pool `39333`, Pure SOLO `39334`, guarded
production submitblock, candidate lifecycle tracking, Pool/SOLO accounting,
guarded payout automation, and snapshot-driven public API/frontend views.

Historical benchmark/runbook material may describe earlier dry-run, submit-off,
or payout-paused milestones. Do not use those old milestone defaults to replace
current production configuration.

For Pure SOLO production, the critical persistent environment is:

```text
/home/ubuntu/pool-pepepow/ops/env/pool-stratum-solo.env
```

and `pepepow-pool-stratum-solo.service` must pass
`ops/scripts/check-solo-production-env.sh` before starting.

Runtime diagnostics must remain bounded. Prefer snapshots, `tail`, and bounded
`rg`; do not perform unbounded raw JSONL scans or use pandas on runtime logs.
