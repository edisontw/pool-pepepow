#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "scripts"))
import pool_health_summary


class PoolHealthSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.old_env = dict(os.environ)
        os.environ.pop("PEPEPOW_ENABLE_REAL_WALLET_PAYOUT", None)
        os.environ.pop("PEPEPOW_ENABLE_REAL_SUBMITBLOCK", None)
        os.environ.pop("PEPEPOW_MIN_PAYOUT", None)
        os.environ.pop("PEPEPOW_POOL_FEE_PERCENT", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp_dir.cleanup()

    def _write_json(self, name, data):
        path = self.tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def _args(self, fmt="json"):
        return [
            "--runtime-dir", str(self.tmp_path),
            "--activity-snapshot", str(self.tmp_path / "activity-snapshot.json"),
            "--rounds-snapshot", str(self.tmp_path / "rounds-snapshot.json"),
            "--payments-snapshot", str(self.tmp_path / "payments-snapshot.json"),
            "--accepted-candidates", str(self.tmp_path / "accepted-candidates.json"),
            "--share-log", str(self.tmp_path / "share-events.jsonl"),
            "--watchdog-snapshot", str(self.tmp_path / "pool-wallet-watchdog.json"),
            "--launch-env", str(self.tmp_path / "launch.env"),
            "--api-pool-snapshot", str(self.tmp_path / "pool-snapshot.json"),
            "--format", fmt,
        ]

    def _run_json(self):
        buf = StringIO()
        with redirect_stdout(buf):
            rc = pool_health_summary.main(self._args("json"))
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())

    def test_summary_reads_existing_snapshots_and_config(self):
        self._write_json("activity-snapshot.json", {
            "meta": {
                "lastShareAt": "2026-06-17T12:00:00Z",
                "realSubmitblockEnabled": True,
            }
        })
        self._write_json("rounds-snapshot.json", {
            "updated_at": "2026-06-17T12:05:00Z",
            "rounds": [{
                "status": "confirmed",
                "submit_timestamp": "2026-06-17T11:55:00Z",
            }],
        })
        self._write_json("payments-snapshot.json", {
            "updated_at": "2026-06-17T12:06:00Z",
            "items": [{
                "wallet": "wallet1",
                "amount": 1000.0,
                "txid": "tx1",
                "paidAt": "2026-06-17T12:02:00Z",
            }],
        })
        self._write_json("accepted-candidates.json", {
            "updated_at": "2026-06-17T12:04:00Z",
            "accepted_candidates": [{
                "candidate_hash": "cand1",
                "lifecycle_status": "confirmed",
                "submit_timestamp": "2026-06-17T11:59:00Z",
            }],
        })
        self._write_json("pool-wallet-watchdog.json", {
            "generatedAt": "2026-06-17T12:07:00Z",
            "status": "ok",
        })
        self._write_json("pool-snapshot.json", {"generatedAt": "2026-06-17T12:08:00Z"})
        (self.tmp_path / "launch.env").write_text(
            "\n".join([
                "PEPEPOW_ENABLE_REAL_WALLET_PAYOUT=true",
                "PEPEPOW_MIN_PAYOUT=1000",
                "PEPEPOW_POOL_FEE_PERCENT=1.5",
            ]),
            encoding="utf-8",
        )

        data = self._run_json()

        self.assertEqual(data["lastAcceptedShare"]["at"], "2026-06-17T12:00:00Z")
        self.assertEqual(data["lastConfirmedPoolBlock"]["at"], "2026-06-17T11:59:00Z")
        self.assertEqual(data["lastSuccessfulPayout"]["at"], "2026-06-17T12:02:00Z")
        self.assertEqual(data["config"]["payoutEnabled"], "true")
        self.assertIs(data["config"]["realSubmitEnabled"], True)
        self.assertEqual(data["config"]["minPayout"], "1000")
        self.assertEqual(data["config"]["poolFeePercent"], "1.5")
        self.assertEqual(data["walletWatchdog"]["status"], "ok")
        self.assertTrue(data["apiSnapshots"]["available"])

    def test_summary_handles_missing_snapshots(self):
        data = self._run_json()

        self.assertFalse(data["roundsSnapshot"]["available"])
        self.assertFalse(data["paymentsSnapshot"]["available"])
        self.assertIsNone(data["lastAcceptedShare"]["at"])
        self.assertIsNone(data["lastConfirmedPoolBlock"]["at"])
        self.assertIsNone(data["lastSuccessfulPayout"]["at"])
        self.assertEqual(data["config"]["payoutEnabled"], "false")
        self.assertEqual(data["config"]["realSubmitEnabled"], "false")
        self.assertFalse(data["walletWatchdog"]["available"])
        self.assertFalse(data["apiSnapshots"]["available"])

    def test_runtime_dir_sets_default_snapshot_paths(self):
        self._write_json("activity-snapshot.json", {"meta": {"lastShareAt": "2026-06-17T12:30:00Z"}})
        buf = StringIO()

        with redirect_stdout(buf):
            rc = pool_health_summary.main(["--runtime-dir", str(self.tmp_path), "--format", "json"])

        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["lastAcceptedShare"]["at"], "2026-06-17T12:30:00Z")
        self.assertEqual(data["roundsSnapshot"]["path"], str(self.tmp_path / "rounds-snapshot.json"))

    def test_live_stratum_wrapper_runs_pool_health(self):
        self._write_json("activity-snapshot.json", {"meta": {"lastShareAt": "2026-06-17T12:00:00Z"}})
        script = Path(__file__).resolve().parents[1] / "ops" / "scripts" / "live-stratum.sh"
        env = dict(os.environ)
        env["PEPEPOW_LIVE_STRATUM_RUNTIME_DIR"] = str(self.tmp_path)

        res = subprocess.run(
            [str(script), "pool-health", "--format", "json"],
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 0, msg=f"stdout: {res.stdout}\nstderr: {res.stderr}")
        data = json.loads(res.stdout.strip())
        self.assertEqual(data["lastAcceptedShare"]["at"], "2026-06-17T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
